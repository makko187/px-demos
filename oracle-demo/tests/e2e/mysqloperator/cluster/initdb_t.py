# Copyright (c) 2020, 2021, Oracle and/or its affiliates.
#
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#

from utils import tutil
from utils import kutil
from utils import dutil
from utils import mutil
import logging
from . import check_apiobjects
from . import check_group
from . import check_adminapi
from . import check_routing
import mysqlsh
import os
import unittest
from utils.tutil import g_full_log
from mysqloperator.controller.utils import b64encode
from utils.optesting import DEFAULT_MYSQL_ACCOUNTS, COMMON_OPERATOR_ERRORS


# TODO check same stuff as check_all() in cluster_t, specially healthness of sidecar
# TODO check if healthchecks and other stuff that rely on accounts work, specially after a clone


class ClusterFromClone(tutil.OperatorTest):
    default_allowed_op_errors = COMMON_OPERATOR_ERRORS

    @classmethod
    def setUpClass(cls):
        cls.logger = logging.getLogger(__name__+":"+cls.__name__)
        super().setUpClass()

        g_full_log.watch_mysql_pod("cloned", "mycluster-0")
        g_full_log.watch_mysql_pod(cls.ns, "mycluster-0")
        g_full_log.watch_mysql_pod(cls.ns, "mycluster-1")
        g_full_log.watch_mysql_pod(cls.ns, "mycluster-2")

    @classmethod
    def tearDownClass(cls):
        g_full_log.stop_watch(cls.ns, "mycluster-2")
        g_full_log.stop_watch(cls.ns, "mycluster-1")
        g_full_log.stop_watch(cls.ns, "mycluster-0")
        g_full_log.stop_watch("cloned", "mycluster-0")

        super().tearDownClass()

    def test_0_create(self):
        kutil.create_user_secrets(
            self.ns, "mypwds", root_user="root", root_host="%", root_pass="sakila")

        # create cluster with mostly default configs
        yaml = """
apiVersion: mysql.oracle.com/v2alpha1
kind: InnoDBCluster
metadata:
  name: mycluster
spec:
  instances: 3
  secretName: mypwds
"""

        kutil.apply(self.ns, yaml)

        self.wait_pod("mycluster-0", "Running")
        self.wait_pod("mycluster-1", "Running")
        self.wait_pod("mycluster-2", "Running")

        self.wait_ic("mycluster", "ONLINE", 3)

        script = open(tutil.g_test_data_dir+"/sql/sakila-schema.sql").read()
        script += open(tutil.g_test_data_dir+"/sql/sakila-data.sql").read()

        mutil.load_script(self.ns, ["mycluster-0", "mysql"], script)

        with mutil.MySQLPodSession(self.ns, "mycluster-0", "root", "sakila") as s:
            s.run_sql("create user clone@'%' identified by 'clonepass'")
            s.run_sql("grant backup_admin on *.* to clone@'%'")

    def test_1_create_clone(self):
        # TODO add support for using different root password between clusters
        kutil.create_ns("clone")
        kutil.create_user_secrets(
            "clone", "pwds", root_user="root", root_host="%", root_pass="sakila")
        kutil.create_user_secrets(
            "clone", "donorpwds", root_user="root", root_host="%", root_pass="sakila")

        # create cluster with mostly default configs
        yaml = """
apiVersion: mysql.oracle.com/v2alpha1
kind: InnoDBCluster
metadata:
  name: copycluster
spec:
  instances: 1
  router:
    instances: 1
  secretName: pwds
  baseServerId: 2000
  initDB:
    clone:
      donorUrl: root@mycluster-0.mycluster-instances.testns.svc.cluster.local:3306
      secretKeyRef:
        name: donorpwds
"""

        kutil.apply("clone", yaml)

        self.wait_pod("copycluster-0", "Running", ns="clone")

        self.wait_ic("copycluster", "ONLINE", 1, ns="clone", timeout=300)

        with mutil.MySQLPodSession(self.ns, "mycluster-0", "root", "sakila") as s:
            orig_tables = [r[0] for r in s.run_sql(
                "show tables in sakila").fetch_all()]

        with mutil.MySQLPodSession("clone", "copycluster-0", "root", "sakila") as s:
            clone_tables = [r[0] for r in s.run_sql(
                "show tables in sakila").fetch_all()]

            # add some data with binlog disabled to make sure that all members of this
            # cluster are cloned
            s.run_sql("set session sql_log_bin=0")
            s.run_sql("create schema unlogged_db")
            s.run_sql("create table unlogged_db.tbl (a int primary key)")
            s.run_sql("insert into unlogged_db.tbl values (42)")
            s.run_sql("set session sql_log_bin=1")

        self.assertEqual(set(orig_tables), set(clone_tables))

        # with self.assertRaises(mysqlsh.Error):
        #     with mutil.MySQLPodSession("clone", "copycluster-0", "root", "sakila") as s:
        #         pass

        check_routing.check_pods(self, "clone", "copycluster", 1)

        # TODO also make sure the source field in the ic says clone and not blank

    def test_2_grow(self):
        kutil.patch_ic("clone", "copycluster", {
                       "spec": {"instances": 2}}, type="merge")

        self.wait_pod("copycluster-1", "Running", ns="clone")

        self.wait_ic("copycluster", "ONLINE", 2, ns="clone")

        # check that the new instance was cloned
        with mutil.MySQLPodSession("clone", "copycluster-1", "root", "sakila") as s:
            self.assertEqual(
                str(s.run_sql("select * from unlogged_db.tbl").fetch_all()), str([[42]]))

    def test_3_routing(self):
        pass  # TODO

    def test_9_destroy(self):
        kutil.delete_ic("clone", "copycluster")
        self.wait_pod_gone("copycluster-1", ns="clone")
        self.wait_pod_gone("copycluster-0", ns="clone")
        self.wait_ic_gone("copycluster", ns="clone")
        kutil.delete_ns("clone")

        kutil.delete_ic(self.ns, "mycluster")

        self.wait_pod_gone("mycluster-2")
        self.wait_pod_gone("mycluster-1")
        self.wait_pod_gone("mycluster-0")
        self.wait_ic_gone("mycluster")


# class ClusterFromCloneErrors(tutil.OperatorTest):
#    pass
# TODO test bad params
# TODO check that errors are reported well
# TODO clone not installed in source
# TODO bad version
        # TODO regression test for bug where a failed clone doesn't abort the pod

@unittest.skipIf(not os.getenv("OPERATOR_TEST_BACKUP_OCI_APIKEY_PATH") or not os.getenv("OPERATOR_TEST_RESTORE_OCI_APIKEY_PATH") or not os.getenv("OPERATOR_TEST_BACKUP_OCI_BUCKET"), "OPERATOR_TEST_BACKUP_OCI_APIKEY_PATH, OPERATOR_TEST_RESTORE_OCI_APIKEY_PATH, OPERATOR_TEST_BACKUP_OCI_BUCKET not set")
class ClusterFromDumpOCI(tutil.OperatorTest):
    """
    Create cluster and initialize from a shell dump stored in an OCI bucket.
    """
    default_allowed_op_errors = COMMON_OPERATOR_ERRORS

    @classmethod
    def setUpClass(cls):
        cls.logger = logging.getLogger(__name__+":"+cls.__name__)
        super().setUpClass()

        g_full_log.watch_mysql_pod(cls.ns, "mycluster-0")
        g_full_log.watch_mysql_pod(cls.ns, "mycluster-1")
        g_full_log.watch_mysql_pod(cls.ns, "mycluster-2")

    @classmethod
    def tearDownClass(cls):
        g_full_log.stop_watch(cls.ns, "mycluster-2")
        g_full_log.stop_watch(cls.ns, "mycluster-1")
        g_full_log.stop_watch(cls.ns, "mycluster-0")

        super().tearDownClass()

    def test_0_prepare(self):
        kutil.create_user_secrets(
            self.ns, "mypwds", root_user="root", root_host="%", root_pass="sakila")

        bucket = os.getenv("OPERATOR_TEST_BACKUP_OCI_BUCKET", "")
        backup_apikey_path = os.getenv(
            "OPERATOR_TEST_BACKUP_OCI_APIKEY_PATH", "")
        restore_apikey_path = os.getenv(
            "OPERATOR_TEST_RESTORE_OCI_APIKEY_PATH", "")

        # create a secret with the api key to access the bucket, which should be
        # stored in the path given in the environment variable
        kutil.create_apikey_secret(
            self.ns, "restore-apikey", restore_apikey_path)
        kutil.create_apikey_secret(
            self.ns, "backup-apikey", backup_apikey_path)

        # create cluster with mostly default configs
        yaml = f"""
apiVersion: mysql.oracle.com/v2alpha1
kind: InnoDBCluster
metadata:
  name: mycluster
spec:
  instances: 1
  secretName: mypwds
  backupProfiles:
  - name: fulldump-oci
    dumpInstance:
      storage:
        ociObjectStorage:
          bucketName: {bucket}
          credentials: backup-apikey
"""

        kutil.apply(self.ns, yaml)

        self.wait_pod("mycluster-0", "Running")
        self.wait_ic("mycluster", "ONLINE", 1)

        script = open(tutil.g_test_data_dir+"/sql/sakila-schema.sql").read()
        script += open(tutil.g_test_data_dir+"/sql/sakila-data.sql").read()

        mutil.load_script(self.ns, "mycluster-0", script)

        self.orig_tables = []
        with mutil.MySQLPodSession(self.ns, "mycluster-0", "root", "sakila") as s:
            self.orig_tables = [r[0]
                                for r in s.run_sql("show tables in sakila").fetch_all()]

        self.dump_name = "dump-test-oci1-20200729-004252"

        # create a dump in a bucket
        yaml = """
apiVersion: mysql.oracle.com/v2alpha1
kind: MySQLBackup
metadata:
  name: initdb-test
spec:
  clusterName: mycluster
  backupProfileName: fulldump-oci
"""
        kutil.apply(self.ns, yaml)

        # wait for backup to be done
        def check_mbk(l):
            for item in l:
                if item["NAME"] == "dump-test-oci1" and item["STATUS"] == "Completed":
                    return item
            return None

        r = self.wait(kutil.ls_mbk, args=(self.ns,),
                      check=check_mbk, timeout=300)

        # destroy the test cluster
        kutil.delete_ic(self.ns, "mycluster")
        self.wait_pod_gone("mycluster-0")
        self.wait_ic_gone("mycluster")

        # delete the pv and pvc for mycluster-0
        kutil.delete_pvc(self.ns, None)
        # TODO ensure the pv was deleted

        kutil.delete_secret(self.ns, "mypwds")

    def test_1_0_create_from_dump(self):
        """
        Create cluster using a shell dump stored in an OCI bucket.
        """
        kutil.create_user_secrets(
            self.ns, "newpwds", root_user="root", root_host="%", root_pass="sakila")

        bucket = os.getenv("OPERATOR_TEST_BACKUP_OCI_BUCKET", "")

        # create cluster with mostly default configs
        yaml = f"""
apiVersion: mysql.oracle.com/v2alpha1
kind: InnoDBCluster
metadata:
  name: newcluster
spec:
  instances: 1
  router:
    instances: 1
  secretName: newpwds
  baseServerId: 2000
  initDB:
    dump:
      name: {self.dump_name}
      storage:
        ociObjectStorage:
          bucketName: {bucket}
          credentials: restore-apikey
"""

        kutil.apply(self.ns, yaml)

        self.wait_pod("newcluster-0", "Running")

        self.wait_ic("newcluster", "ONLINE", 1, timeout=600)

        with mutil.MySQLPodSession(self.ns, "newcluster-0", "root", "sakila") as s:
            tables = [r[0]
                      for r in s.run_sql("show tables in sakila").fetch_all()]

            self.assertEqual(set(self.orig_tables), set(tables))

            # add some data with binlog disabled to allow testing that new
            # members added to this cluster use clone for provisioning
            s.run_sql("set session sql_log_bin=0")
            s.run_sql("create schema unlogged_db")
            s.run_sql("create table unlogged_db.tbl (a int primary key)")
            s.run_sql("insert into unlogged_db.tbl values (42)")
            s.run_sql("set session sql_log_bin=1")

        check_routing.check_pods(self, self.ns, "newcluster", 1)

        # TODO also make sure the source field in the ic says clone and not blank

    def test_1_1_grow(self):
        """
        Ensures that a cluster created from a dump can be scaled up properly
        """
        kutil.patch_ic(self.ns, "newcluster", {
                       "spec": {"instances": 2}}, type="merge")

        self.wait_pod("newcluster-1", "Running")

        self.wait_ic("newcluster", "ONLINE", 2)

        # check that the new instance was provisioned through clone and not incremental
        with mutil.MySQLPodSession(self.ns, "newcluster-1", "root", "sakila") as s:
            self.assertEqual(
                str(s.run_sql("select * from unlogged_db.tbl").fetch_all()), str([[42]]))

    def test_1_2_destroy(self):
        kutil.delete_ic(self.ns, "newcluster")

        self.wait_pod_gone("mycluster-1")
        self.wait_pod_gone("mycluster-0")
        self.wait_ic_gone("mycluster")

    def test_2_create_from_dump_options(self):
        """
        Create cluster using a shell dump with additional options passed to the
        load command.
        """

        bucket = os.getenv("OPERATOR_TEST_BACKUP_OCI_BUCKET", "")

        # create cluster with mostly default configs
        yaml = f"""
apiVersion: mysql.oracle.com/v2alpha1
kind: InnoDBCluster
metadata:
  name: newcluster
spec:
  instances: 1
  router:
    instances: 1
  secretName: newpwds
  baseServerId: 3000
  initDB:
    dump:
      name: {self.dump_name}
      options:
        includeSchemas:
        - sakila
      storage:
        ociObjectStorage:
          bucketName: {bucket}
          credentials: restore-apikey
"""

        kutil.apply(self.ns, yaml)

        self.wait_pod("newcluster-0", "Running")

        self.wait_ic("newcluster", "ONLINE", 1, timeout=600)

        with mutil.MySQLPodSession(self.ns, "newcluster-0", "root", "sakila") as s:
            tables = [r[0]
                      for r in s.run_sql("show tables in sakila").fetch_all()]

            self.assertEqual(set(self.orig_tables), set(tables))

        check_routing.check_pods(self, self.ns, "newcluster", 1)

    def test_9_destroy(self):
        kutil.delete_ic(self.ns, "mycluster")

        self.wait_pod_gone("mycluster-2")
        self.wait_pod_gone("mycluster-1")
        self.wait_pod_gone("mycluster-0")
        self.wait_ic_gone("mycluster")

        kutil.delete_secret(self.ns, "restore-apikey")
        kutil.delete_secret(self.ns, "backup-apikey")

# class ClusterFromDumpLocal(tutil.OperatorTest):
#    pass


class ClusterFromDumpErrors(tutil.OperatorTest):
    pass
