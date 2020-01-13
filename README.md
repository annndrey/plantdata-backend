# plantdata-backend

The Plantdata API

To use the service, first get the auth token,

```
POST https://dev.plantdata.fermata.tech:5598/api/v2/token

{"username":"user@site.com", "password":"userpassword"}
```

Then add header `'Authorization': 'Bearer Replace-With-Auth-Token'` to every request