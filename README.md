# Zellovest

Here the first user is assigned access to the system via CLI seed script. Then this user can invite other users.

Situations when celery beat is needed to act like janitor cleaning up db rows in uploads table with pending status that has past the expiry time.

![](resources/image.png)


Fixes needed:

1. Manual file upload - When user clicks cancel, once the file is completely uploaded to GCS bucket, but before /upload/{upload_id}/complete endpoint, that object remains in the bucket, not deleted. Handle this

2. Set up celery beat as janitor to clean up the mess of pending status db inserts in uploads table that has passed expiry limit.



### GET /uploads/{id} :
Imagine you upload Resume_Zameer_U.pdf. Here’s the file’s journey, and what the endpoint says at each stop. ({id} is the upload_id from step 1 — think of it as the file’s tracking number.)

Step 1 — You drop the file. Frontend calls POST /uploads/init → backend replies 201 with a tracking number, say caeb847a…. A row is written in the database: status = pending (“we’re waiting for the bytes”).

Step 2 — Bytes fly to Google. The browser PUTs the PDF straight to GCS. Nobody asks the backend anything during this.

Step 3 — Your code asks: “did it arrive?” Frontend calls POST /uploads/{id}/complete. Backend checks GCS, flips the row to staged (“bytes verified, worker notified”), and a background worker picks it up (processing), then finishes extraction (completed) — or something breaks (failed).

Now the problem this endpoint solves: after step 3, the frontend is staring at a row that says “Processing…” — but is the worker actually working? Done? Crashed 5 minutes ago? The frontend can’t know, because everything after complete happens silently in the background.

So it asks, every 3 seconds:

"GET /uploads/caeb847a… → “status: processing”
GET /uploads/caeb847a… → “status: processing”
GET /uploads/caeb847a… → “status: completed” ✅ → UI flips to ✓ Done
"

And if things went wrong instead:

'GET /uploads/caeb847a… → “status: failed, error: blob absent from GCS” → UI shows ✗ with that exact reason.'

##### Why not avoid it
Without it, the UI has two bad options after complete: freeze on “Processing…” forever (user has no idea if extraction worked), or blindly declare “Done” the moment bytes land in GCS (declaring victory before extraction even starts — which is what the old simulated UI did).

