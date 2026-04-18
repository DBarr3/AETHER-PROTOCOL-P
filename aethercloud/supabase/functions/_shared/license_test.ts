import {
  generateLicenseKey,
  isValidEmail,
  isDisposableEmail,
} from "./license.ts";

Deno.test("generateLicenseKey produces AETH-CLD-XXXX-XXXX-XXXX format", () => {
  const key = generateLicenseKey();
  const re = /^AETH-CLD-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$/;
  if (!re.test(key)) throw new Error(`Bad format: ${key}`);
});

Deno.test("generateLicenseKey produces different keys on successive calls", () => {
  const a = generateLicenseKey();
  const b = generateLicenseKey();
  if (a === b) throw new Error("Collision in 2 calls — not random enough");
});

Deno.test("isValidEmail accepts valid addresses", () => {
  for (const e of ["a@b.c", "user@example.com", "first.last+tag@sub.domain.io"]) {
    if (!isValidEmail(e)) throw new Error(`Rejected valid: ${e}`);
  }
});

Deno.test("isValidEmail rejects malformed addresses", () => {
  for (const e of ["", "foo", "foo@", "@bar", "foo bar@baz.com", "foo@bar"]) {
    if (isValidEmail(e)) throw new Error(`Accepted invalid: ${e}`);
  }
});

Deno.test("isDisposableEmail blocks mailinator.com", () => {
  if (!isDisposableEmail("x@mailinator.com")) throw new Error("Should block");
});

Deno.test("isDisposableEmail is case-insensitive on domain", () => {
  if (!isDisposableEmail("x@MAILINATOR.COM")) throw new Error("Should block uppercase");
});

Deno.test("isDisposableEmail allows gmail.com", () => {
  if (isDisposableEmail("x@gmail.com")) throw new Error("Should allow");
});

Deno.test("isDisposableEmail allows proton.me (paid users allowed)", () => {
  if (isDisposableEmail("x@proton.me")) throw new Error("Should allow Proton");
});
