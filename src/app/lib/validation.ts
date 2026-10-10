export interface CredentialErrors {
  email?: string;
  password?: string;
  confirm?: string;
}

const EMAIL_SHAPE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
export const MIN_PASSWORD_LENGTH = 8;

/**
 * Quick checks that save a round trip. The server is still the authority: it applies the same rules again and its
 * answer is shown if it disagrees.
 */
export function validateCredentials(mode: "login" | "register", email: string, password: string, confirm?: string): CredentialErrors {
  const errors: CredentialErrors = {};
  if (!email.trim()) errors.email = "Enter your email address.";
  else if (!EMAIL_SHAPE.test(email.trim())) errors.email = "Enter a valid email address, like name@example.com.";

  if (!password) errors.password = "Enter your password.";
  else if (mode === "register" && password.length < MIN_PASSWORD_LENGTH) {
    errors.password = `Use at least ${MIN_PASSWORD_LENGTH} characters (you have ${password.length}).`;
  }
  // Registering asks for the password twice, so a typo is caught here instead of being saved. Logging in never asks twice.
  if (mode === "register" && confirm !== undefined && !errors.password && confirm !== password) {
    errors.confirm = confirm ? "The two passwords do not match." : "Type the password again to confirm it.";
  }
  return errors;
}

/** Pick out per-field problems the server reported (for example from a 422), keyed by form field. */
export function serverFieldErrors(problems: { field: string; message: string }[]): CredentialErrors {
  const errors: CredentialErrors = {};
  for (const problem of problems) {
    if (problem.field === "email" && !errors.email) errors.email = problem.message;
    if (problem.field === "password" && !errors.password) errors.password = problem.message;
  }
  return errors;
}
