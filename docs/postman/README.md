# Postman collection

`finsight.postman_collection.json` walks through the API: health, register, login, upload, status, every result, a category correction, refusal without a token, delete and logout.

1. Postman -> Import -> choose the JSON file.
2. Open the collection's Variables: set `base_url` (local `http://localhost:8000`, or the live site's address) and, if you like, a throwaway `email`.
3. In the upload request choose `data/sample_descriptions_only.csv` for the `file` field.
4. Run the requests in order (or use the Collection Runner). Re-send "Status" until it says completed before the result requests.

The cookie-based endpoints (`/api/auth/refresh`) are checked by `scripts/check_cookie_flow.py` instead, because they depend on browser cookie rules.
