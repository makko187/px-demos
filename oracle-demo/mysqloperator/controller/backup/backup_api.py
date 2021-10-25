# Copyright (c) 2020, 2021, Oracle and/or its affiliates.
#
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#

from .. import consts
from ..api_utils import dget_dict, dget_str, dget_int, dget_bool, dget_list, ApiSpecError
from ..kubeutils import api_core, api_apps, api_customobj, ApiException
from ..storage_api import StorageSpec
from typing import Optional, cast


class Snapshot:
    storage: Optional[StorageSpec] = None

    def add_to_pod_spec(self, pod_spec: dict, container_name: str) -> None:
        self.storage.add_to_pod_spec(pod_spec, container_name)

    def parse(self, spec: dict, prefix: str) -> None:
        storage = dget_dict(spec, "storage", prefix)
        self.storage = StorageSpec(
            ["ociObjectStorage", "persistentVolumeClaim"])
        self.storage.parse(storage, prefix+".storage")


class DumpInstance:
    dumpOptions: dict = {}  # dict with options for dumpInstance()
    storage: Optional[StorageSpec] = None  # StorageSpec

    def add_to_pod_spec(self, pod_spec: dict, container_name: str) -> None:
        self.storage.add_to_pod_spec(pod_spec, container_name)

    def parse(self, spec: dict, prefix: str) -> None:
        self.options = dget_dict(spec, "dumpOptions", prefix, {})

        storage = dget_dict(spec, "storage", prefix)
        self.storage = StorageSpec()
        self.storage.parse(storage, prefix+".storage")


class BackupProfile:
    name: str = ""
    dumpInstance: Optional[DumpInstance] = None
    snapshot: Optional[Snapshot] = None

    def add_to_pod_spec(self, pod_spec: dict, container_name: str) -> None:
        if self.snapshot:
            return self.snapshot.add_to_pod_spec(pod_spec, container_name)
        if self.dumpInstance:
            return self.dumpInstance.add_to_pod_spec(pod_spec, container_name)
        assert 0

    def parse(self, spec: dict, prefix: str) -> None:
        self.name = dget_str(spec, "name", prefix)
        prefix += "." + self.name
        method_spec = dget_dict(spec, "dumpInstance", prefix, {})
        if method_spec:
            self.dumpInstance = DumpInstance()
            self.dumpInstance.parse(method_spec, prefix+".dumpInstance")
        method_spec = dget_dict(spec, "snapshot", prefix, {})
        if method_spec:
            self.snapshot = Snapshot()
            self.snapshot.parse(method_spec, prefix+".snapshot")

        if self.dumpInstance and self.snapshot:
            raise ApiSpecError(
                f"Only one of dumpInstance or snapshot may be set in {prefix}")

        if not self.dumpInstance and not self.snapshot:
            raise ApiSpecError(
                f"One of dumpInstance or snapshot must be set in a {prefix}")


class BackupSchedule:
    name: str = ""
    backupProfileName: str = ""
    schedule = None


class MySQLBackupSpec:
    clusterName: str = ""
    backupProfileName: str = ""
    backupProfile = None
    deleteBackupData: bool = False
    operator_image: str = ""
    operator_image_pull_policy: str = ""
    image_pull_secrets: Optional[str] = None
    service_account_name: Optional[str] = None

    def __init__(self, namespace: str, name: str, spec: dict):
        self.namespace = namespace
        self.name = name
        self.parse(spec)

    def add_to_pod_spec(self, pod_spec: dict, container_name: str) -> None:
        return self.backupProfile.add_to_pod_spec(pod_spec, container_name)

    def parse(self, spec: dict) -> Optional[ApiSpecError]:
        self.clusterName = dget_str(spec, "clusterName", "spec")
        self.backupProfileName = dget_str(
            spec, "backupProfileName", "spec", default_value="")
        self.backupProfile = self.parse_backup_profile(
            dget_dict(spec, "backupProfile", "spec", {}), "spec.backupProfile")
        self.deleteBackupData = dget_bool(
            spec, "deleteBackupData", "spec", default_value=False)

        print(f"self.clusterName={self.clusterName} self.backupProfileName={self.backupProfileName} self.backupProfile={self.backupProfile}  self.deleteBackupData={self.deleteBackupData}")
        if self.backupProfileName and self.backupProfile:
            raise ApiSpecError(
                f"Only one of spec.backupProfileName or spec.backupProfile must be set")
        if not self.backupProfileName and not self.backupProfile:
            raise ApiSpecError(
                f"One of spec.backupProfileName or spec.backupProfile must be set")

        try:
            from ..innodbcluster.cluster_api import InnoDBCluster

            cluster = InnoDBCluster.read(self.namespace, self.clusterName)
        except ApiException as e:
            if e.status == 404:
                return ApiSpecError(f"Invalid clusterName {self.namespace}/{self.clusterName}")
            raise

        self.operator_image = cluster.parsed_spec.operator_image
        self.operator_image_pull_policy = cluster.parsed_spec.operator_image_pull_policy
        self.image_pull_secrets = cluster.parsed_spec.image_pull_secrets
        self.service_account_name = cluster.parsed_spec.service_account_name

        if self.backupProfileName:
            self.backupProfile = cluster.parsed_spec.get_backup_profile(
                self.backupProfileName)
            if not self.backupProfile:
                return ApiSpecError(f"Invalid backupProfileName '{self.backupProfileName}' in cluster {self.namespace}/{self.clusterName}")

        print(f"backupProfile={self.backupProfile}")

    def parse_backup_profile(self, profile: dict, prefix: str) -> Optional[BackupProfile]:
        # TODO ?
        if profile:
            p = BackupProfile()
            p.parse(profile, prefix)
            return p
        return None


class MySQLBackup:
    def __init__(self, backup: dict):
        self.obj: dict = backup

        # self.namespace and self.name here will call the getters, which in turn will
        # look into self.obj['metadata']
        self.parsed_spec = MySQLBackupSpec(
            self.namespace, self.name, self.spec)

    def __str__(self) -> str:
        return f"{self.namespace}/{self.name}"

    def __repr__(self) -> str:
        return f"<MySQLBackup {self.name}>"

    def get_cluster(self):
        try:
            from ..innodbcluster.cluster_api import InnoDBCluster

            cluster = InnoDBCluster.read(self.namespace, self.cluster_name)
        except ApiException as e:
            if e.status == 404:
                return ApiSpecError(f"Invalid clusterName {self.namespace}/{self.cluster_name}")
            raise
        return cluster

    @classmethod
    def read(cls, name: str, namespace: str) -> 'MySQLBackup':
        return MySQLBackup(cast(dict, api_customobj.get_namespaced_custom_object(
            consts.GROUP, consts.VERSION, namespace, consts.MYSQLBACKUP_PLURAL, name)))

    @property
    def metadata(self) -> dict:
        return self.obj["metadata"]

    @property
    def spec(self) -> dict:
        return self.obj["spec"]

    @property
    def status(self) -> dict:
        if "status" in self.obj:
            return self.obj["status"]
        return {}

    @property
    def name(self) -> str:
        return self.metadata["name"]

    @property
    def namespace(self) -> str:
        return self.metadata["namespace"]

    @property
    def cluster_name(self) -> str:
        return self.parsed_spec.clusterName

    def get_profile(self):
        if self.parsed_spec.backupProfile:
            return self.parsed_spec.backupProfile

        cluster = self.get_cluster()
        profile = cluster.parsed_spec.get_backup_profile(self.parsed_spec.backupProfileName)
        if not profile:
            raise Exception(
                f"Unknown backup profile {self.parsed_spec.backupProfileName} in cluster {self.namespace}/{self.parsed_spec.clusterName}")

        return profile

    def set_started(self, backup_name: str, start_time: str) -> None:
        patch = {"status": {
            "status": "Running",
            "startTime": start_time,
            "output": backup_name
        }}
        self.obj = cast(dict, api_customobj.patch_namespaced_custom_object_status(
            consts.GROUP, consts.VERSION, self.namespace, consts.MYSQLBACKUP_PLURAL, self.name, body=patch))

    def set_succeeded(self, backup_name: str, start_time: str, end_time: str, info: dict) -> None:
        import dateutil.parser as dtp

        elapsed = dtp.isoparse(end_time) - dtp.isoparse(start_time)
        hours, seconds = divmod(elapsed.total_seconds(), 3600)
        minutes, seconds = divmod(seconds, 60)

        patch = {"status": {
            "status": "Completed",
            "startTime": start_time,
            "completionTime": end_time,
            "elapsedTime": f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}",
            "output": backup_name
        }}
        patch["status"].update(info)
        self.obj = cast(dict, api_customobj.patch_namespaced_custom_object_status(
            consts.GROUP, consts.VERSION, self.namespace, consts.MYSQLBACKUP_PLURAL, self.name, body=patch))

    def set_failed(self, backup_name: str, start_time: str, end_time: str, error: Exception) -> None:
        import dateutil.parser as dtp

        elapsed = dtp.isoparse(end_time) - dtp.isoparse(start_time)
        hours, seconds = divmod(elapsed.total_seconds(), 3600)
        minutes, seconds = divmod(seconds, 60)

        patch = {"status": {
            "status": "Error",
            "startTime": start_time,
            "completionTime": end_time,
            "elapsedTime": f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}",
            "message": str(error),
            "output": backup_name
        }}
        self.obj = cast(dict, api_customobj.patch_namespaced_custom_object_status(
            consts.GROUP, consts.VERSION, self.namespace, consts.MYSQLBACKUP_PLURAL, self.name, body=patch))
