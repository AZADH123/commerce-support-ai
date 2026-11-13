"""Business services package.

Services own the domain rules (ownership, eligibility, state transitions) and
are called by both the API routes and the agent tools, so the same rules hold
no matter which entry point a request arrives through.
"""
