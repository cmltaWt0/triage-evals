# shop-deploy

Helm values for the shop. Production runs the image tags in `values/production.yaml`.
The cluster's nodes are managed by the hosting provider; their packages are not in this repository.
The API's environment comes from the secret `shop-api-env`, which is made by hand in the cluster and is not in this repository.
