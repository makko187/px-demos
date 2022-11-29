From: https://rajanieshkaushikk.com/2021/02/27/how-to-deploy-sql-server-containers-to-a-kubernetes-cluster-for-high-availability/

# deploy storageclass and services
kubectl apply -f 1-sql-sc-pvc.yaml
kubectl apply -f 3-sql-svc.yaml

# Deploy secret: use complex password
kubectl create secret generic mssql-secret --from-literal=SA_PASSWORD="Welcome@0001234567"
 
# Deploy the SQL Server 2019 container
kubectl apply -f 2-sql-deploy.yaml

# List the running pods and services
kubectl get pods
kubectl get services
 
# TO fetch details about the POD
kubectl describe pod mssql
 
# Copy the sample database to the pod
# You can download the AdventureWorks2014.bak file from this URL
# https://github.com/Microsoft/sql-server-samples/releases/download/adventureworks/AdventureWorks2014.bak
 
# Use curl command to download the database if you are using Linux otherwise use direct download link
# curl -L -o AdventureWorks2014.bak "https://github.com/Microsoft/sql-server-samples/releases/download/adventureworks/AdventureWorks2014.bak"
 
# Retrieve pod name to variable
podname=$(kubectl get pods | grep mssql | cut -c1-32)
#Display the variable name
echo $podname
#Copy the backup file to POD in AKS. In Linux SQL server is installed on this path. We use this POD Name: /var/opt/mssql/data/ to access the specific directory in the POD
fullpath=${podname}":/var/opt/mssql/data/AdventureWorks2014.bak"
# Just to verify the path. 
echo $fullpath
# just to echo what are we doing
echo Copying AdventureWorks2014 database to pod $podname
 
# Remember to specify the path if your project is running in different directory otherwise we can remove this path and make it kubectl cp AdventureWorks2014.bak  $fullpath
kubectl cp AdventureWorks2014.bak ${fullpath}
 
# Connect to the SQL Server pod with Azure Data Studio
# Retrieve external IP address
ip=$(kubectl get services | grep mssql | cut -c45-60)
echo $ip
  
# Simulate a failure by killing the pod. Delete pod exactkly does it.
kubectl delete pod ${podname}
 
# Wait one second
echo Waiting 3 second to show newly started pod
sleep 3
 
# now retrieve the running POD and you see the that POD name is different because Kubernetes recreated 
#it after we deleted the earlier one
echo Retrieving running pods
kubectl get pods
 
# Get all of the running components
kubectl get all
 
# for Troubelshooting purpose you can use this command to view the events  
 
kubectl describe pod -l app=mssql
  
# Display the container logs
kubectl logs -l app=mssql
