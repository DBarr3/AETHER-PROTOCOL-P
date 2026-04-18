export const metadata = { title: "Welcome to AetherCloud" };

export default function SuccessPage() {
  return (
    <main className="max-w-2xl mx-auto px-4 py-24 text-center">
      <h1 className="text-3xl font-bold">You're in.</h1>
      <p className="mt-4 text-gray-600">
        Check your email for your license key. It should arrive within a minute from{" "}
        <strong>no-reply@aethersystems.net</strong>.
      </p>
      <p className="mt-6 text-sm text-gray-500">
        Didn't get it? Check spam, or{" "}
        <a href="mailto:support@aethersystems.net" className="underline">email support</a>.
      </p>
      <p className="mt-12">
        <a href="/" className="text-sm underline text-gray-600">Back to pricing</a>
      </p>
    </main>
  );
}
