/**
 * Identity context — `AccessToken` Value Object.
 *
 * Wraps a bearer token and exposes domain behaviour (claim inspection, scope
 * checks). Decoding reads claims for display/authorisation decisions only; the
 * cryptographic signature/audience/issuer are validated upstream (APIM / Entra
 * JWKS). Defined entirely by its raw value, so it is a Value Object.
 */
export class AccessToken {
  private constructor(
    public readonly raw: string,
    public readonly claims: Record<string, unknown> | null
  ) {}

  /**
   * Build an AccessToken from an HTTP `Authorization` header value.
   * Returns null when no `Bearer <token>` is present.
   */
  static fromAuthorizationHeader(header: unknown): AccessToken | null {
    if (typeof header !== "string" || !header.toLowerCase().startsWith("bearer ")) {
      return null;
    }
    const raw = header.slice(7).trim();
    return new AccessToken(raw, AccessToken.decodeClaims(raw));
  }

  /**
   * Whether the token carries the given delegated scope (`scp`) or app role
   * (`roles`). When claims cannot be decoded, the check defers to upstream
   * validation (APIM) and does not block.
   */
  hasScope(scope: string): boolean {
    if (!this.claims) {
      return true;
    }
    const scp = typeof this.claims.scp === "string" ? this.claims.scp.split(" ") : [];
    const roles = Array.isArray(this.claims.roles) ? (this.claims.roles as string[]) : [];
    return [...scp, ...roles].includes(scope);
  }

  private static decodeClaims(token: string): Record<string, unknown> | null {
    const parts = token.split(".");
    if (parts.length < 2) {
      return null;
    }
    try {
      const payload = Buffer.from(parts[1], "base64url").toString("utf8");
      return JSON.parse(payload) as Record<string, unknown>;
    } catch {
      return null;
    }
  }
}
