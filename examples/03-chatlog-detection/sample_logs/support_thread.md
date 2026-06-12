User: the nightly export job failed again, can you take a look?
Agent: Looking now. The traceback points at the S3 upload step — looks like the credentials expired overnight.
User: didn't we rotate those last week?
Agent: We rotated the API keys, but the export job uses a separate IAM role whose session token has a 12-hour cap. That's what timed out.
User: so what's the fix?
Agent: Two options: bump the token lifetime to 24h, or have the job refresh the token mid-run. The refresh is safer — a long-lived token is a bigger blast radius if it leaks.
User: let's do the refresh then
Agent: On it. I'll add a refresh call before the upload step and redeploy. Should be live within the hour.
User: thanks, appreciate the quick turnaround
Agent: anytime.
