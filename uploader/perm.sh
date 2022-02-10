#!/bin/bash

kubectl exec --tty --stdin px-pvc-pod -- chmod 777 ./server/php/files
