import json
from typing import Dict, Any
import requests
from jose import jwt
from fastapi import HTTPException, status
from app.infrastructure.config import settings

class Auth0Validator:
    """Helper to validate Auth0 RS256 tokens."""
    
    def __init__(self):
        self.domain = settings.AUTH0_DOMAIN
        self.audience = settings.AUTH0_AUDIENCE
        self.jwks_url = f"https://{self.domain}/.well-known/jwks.json"
        self._jwks = None

    def get_jwks(self):
        if not self._jwks:
            # Critical: protect the whole request path from hanging on network calls.
            # If Auth0 JWKS is slow/unreachable, we fall back to local HS256 tokens.
            response = requests.get(self.jwks_url, timeout=5)
            response.raise_for_status()
            self._jwks = response.json()
        return self._jwks

    def validate_token(self, token: str) -> Dict[str, Any]:
        try:
            unverified_header = jwt.get_unverified_header(token)
            # If this isn't an RS256 token, it can't be an Auth0 JWT.
            # This also avoids hanging on JWKS calls for locally-issued tokens.
            if unverified_header.get("alg") != "RS256":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid Auth0 token: unexpected alg",
                )
            jwks = self.get_jwks()
            rsa_key = {}
            for key in jwks["keys"]:
                if key["kid"] == unverified_header["kid"]:
                    rsa_key = {
                        "kty": key["kty"],
                        "kid": key["kid"],
                        "use": key["use"],
                        "n": key["n"],
                        "e": key["e"]
                    }
            if rsa_key:
                payload = jwt.decode(
                    token,
                    rsa_key,
                    algorithms=["RS256"],
                    audience=self.audience,
                    issuer=f"https://{self.domain}/"
                )
                return payload
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid Auth0 token: {str(e)}"
            )
        
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unable to find appropriate key in JWKS"
        )

auth0_validator = Auth0Validator()
