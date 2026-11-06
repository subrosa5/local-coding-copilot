# API errors

A RATE_LIMITED response requires exponential backoff and an explicit retry delay.
An INVALID_INSTRUMENT error must not be retried with the same payload.

Clients include request_id when contacting support about a failed API request.
