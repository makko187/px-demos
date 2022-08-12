
#Install external snapshot CRDs for FA snapshots:
#https://github.com/kubernetes-csi/external-snapshotter/tree/master/client/config/crd


kubectl apply -f snapshot.storage.k8s.io_volumesnapshotclasses.yaml

kubectl apply -f snapshot.storage.k8s.io_volumesnapshotcontents.yaml

kubectl apply -f snapshot.storage.k8s.io_volumesnapshots.yaml

