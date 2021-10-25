# Copyright (c) 2020, 2021, Oracle and/or its affiliates.
#
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#

from .base import BaseEnvironment
import os
import subprocess


class K3dEnvironment(BaseEnvironment):
    name = "k3d"

    def load_images(self, images):
        loaded = []
        for img, is_latest in images:
            md = open(img+".txt")
            image_id = md.readline().strip()
            image_repo_tag = md.readline().strip()
            self.load_image(image_repo_tag, image_id)

    def load_image(self, repo_tag, id):
        print(f"Loading image {repo_tag} ({id})")
        cmd = f"k3d image import {repo_tag} -c k3s-default"
        print(cmd)
        subprocess.check_call(cmd, shell=True)

    def start_cluster(self, nodes, version):
        assert version is None

        #regpath = os.path.join(os.path.dirname(__file__), "k3d-registries.yaml")
        # , "--volume", regpath+":/etc/rancher/k3s/registries.yaml"]
        args = ["k3d", "cluster", "create", "k3s-default"]
        subprocess.check_call(args)

        # connect network of the cluster to the local image registry
        #subprocess.call(["docker", "network", "connect", "k3d-k3s-cluster", "registry.localhost"])

    def stop_cluster(self):
        args = ["k3d", "cluster", "stop", "k3s-default"]
        subprocess.check_call(args)

    def delete_cluster(self):
        args = ["k3d", "cluster", "delete", "k3s-default"]
        subprocess.check_call(args)
