#https://kubernetes.io/docs/tutorials/stateful-application/cassandra/

#1 Apply cassandra yaml 
kubectl apply -f cassandra-service.yaml

#2 Get the Cassandra StatefulSet:
kubectl get statefulset cassandra

#3 Check Pods
kubectl get pods -l="app=cassandra"

#4 Run the Cassandra nodetool inside the first Pod, to display the status of the ring.
kubectl exec -it cassandra-0 -- nodetool status

##The response should look something like:
Datacenter: DC1-K8Demo
======================
Status=Up/Down
|/ State=Normal/Leaving/Joining/Moving
--  Address     Load       Tokens       Owns (effective)  Host ID                               Rack
UN  172.17.0.5  83.57 KiB  32           74.0%             e2dd09e6-d9d3-477e-96c5-45094c08db0f  Rack1-K8Demo
UN  172.17.0.4  101.04 KiB  32           58.8%             f89d6835-3a42-4419-92b3-0e62cae1479c  Rack1-K8Demo
UN  172.17.0.6  84.74 KiB  32           67.1%             a6a1e8c2-3dc5-4417-b1a0-26507af2aaad  Rack1-K8Demo


#5 Modifying the Cassandra StatefulSet
kubectl edit statefulset cassandra

#change is the replicas field = 4. 
# Please edit the object below. Lines beginning with a '#' will be ignored,
# and an empty file will abort the edit. If an error occurs while saving this file will be
# reopened with the relevant failures.
#
apiVersion: apps/v1
kind: StatefulSet
metadata:
  creationTimestamp: 2016-08-13T18:40:58Z
  generation: 1
  labels:
  app: cassandra
  name: cassandra
  namespace: default
  resourceVersion: "323"
  uid: 7a219483-6185-11e6-a910-42010a8a0fc0
spec:
  replicas: 3


#6 Check scaled pods
kubectl get statefulset cassandra
NAME        READY   AGE
cassandra   0/4     22h

#7 Check scaled pods
kubectl get pods -o  wide
NAME          READY   STATUS    RESTARTS   AGE     IP               NODE         NOMINATED NODE   READINESS GATES
cassandra-0   0/1     Running   0          22h     192.168.70.244   k8-worker3   <none>           <none>
cassandra-1   0/1     Running   0          22h     192.168.86.137   k8-worker2   <none>           <none>
cassandra-2   0/1     Running   3          22h     192.168.80.169   k8-worker1   <none>           <none>
cassandra-3   0/1     Running   0          3m22s   192.168.70.245   k8-worker3   <none>           <none>

#8 Clean UP Statefulset
grace=$(kubectl get pod cassandra-0 -o=jsonpath='{.spec.terminationGracePeriodSeconds}') \
  && kubectl delete statefulset -l app=cassandra \
  && echo "Sleeping ${grace} seconds" 1>&2 \
  && sleep $grace \
  && kubectl delete persistentvolumeclaim -l app=cassandra

#9 Delete the Service you set up for Cassandra:
kubectl delete service -l app=cassandra


==========
New Procedure:
https://portworx.com/kubernetes-cassandra-run-ha-cassandra-rancher-kubernetes-engine/

1. Deploy Storage Class
2. Deploy Service
3. Deploy Cassandra sts
4. Scale Cassandra to 4
	kubectl edit sts cassandra
5. Populating sample data

Let's populate the database with some sample data by accessing the first node of the Cassandra cluster. We will do this by invoking Cassandra shell, cqlsh in one of the pods.
 	kubectl exec -it cassandra-0 -- cqlsh

6. Populate with data
CREATE KEYSPACE classicmodels WITH REPLICATION = { 'class' : 'SimpleStrategy', 'replication_factor' : 3 };
	
CONSISTENCY QUORUM;
Consistency level set to QUORUM.

use classicmodels;

CREATE TABLE offices (officeCode text PRIMARY KEY, city text, phone text, addressLine1 text, addressLine2 text, state text, country text, postalCode text, territory text);

INSERT into offices(officeCode, city, phone, addressLine1, addressLine2, state, country ,postalCode, territory) values 
	('1','San Francisco','+1 650 219 4782','100 Market Street','Suite 300','CA','USA','94080','NA');

INSERT into offices(officeCode, city, phone, addressLine1, addressLine2, state, country ,postalCode, territory) values 
	('2','Boston','+1 215 837 0825','1550 Court Place','Suite 102','MA','USA','02107','NA');

INSERT into offices(officeCode, city, phone, addressLine1, addressLine2, state, country ,postalCode, territory) values 	
	('3','NYC','+1 212 555 3000','523 East 53rd Street','apt. 5A','NY','USA','10022','NA');

INSERT into offices(officeCode, city, phone, addressLine1, addressLine2, state, country ,postalCode, territory) values 
	('4','Paris','+33 14 723 4404','43 Rue Jouffroy abbans', NULL ,NULL,'France','75017','EMEA');

INSERT into offices(officeCode, city, phone, addressLine1, addressLine2, state, country ,postalCode, territory) values 		
	('5','Tokyo','+81 33 224 5000','4-1 Kioicho',NULL,'Chiyoda-Ku','Japan','102-8578','Japan');

INSERT into offices(officeCode, city, phone, addressLine1, addressLine2, state, country ,postalCode, territory) values 
	('6','Sydney','+61 2 9264 2451','5-11 Wentworth Avenue','Floor #2',NULL,'Australia','NSW 2010','APAC');

INSERT into offices(officeCode, city, phone, addressLine1, addressLine2, state, country ,postalCode, territory) values 
	('7','London','+44 20 7877 2041','25 Old Broad Street','Level 7',NULL,'UK','EC2N 1HN','EMEA');

INSERT into offices(officeCode, city, phone, addressLine1, addressLine2, state, country ,postalCode, territory) values 
	('8','Mumbai','+91 22 8765434','BKC','Building 2',NULL,'MH','400051','APAC');

7. Check data:
	SELECT * FROM classicmodels.offices;

8. Exit Cassandra: type 'exit'

9. Check Data Again:
	kubectl exec cassandra-0 -- cqlsh -e 'select * from classicmodels.offices'

10. Observe that the data is still there and all the content is intact! We can also run the nodetool again to see that the new node is indeed a part of the StatefulSet.
 
$kubectl exec cassandra-1 -- nodetool status
Datacenter: DC1
===============
Status=Up/Down
|/ State=Normal/Leaving/Joining/Moving
--  Address          Load       Tokens       Owns (effective)  Host ID                               Rack
UN  192.168.148.159  100.44 KiB  256          100.0%            fd1610c8-7745-49eb-b801-983cde4e1b85  Rack1
UN  192.168.81.245   186.62 KiB  256          100.0%            b84b4537-61fe-41bc-9009-d881fcc38f46  Rack1
UN  192.168.172.87   196.54 KiB  256          100.0%            94ef766a-6100-464b-abcb-f9153


