export const metadata = { title: "Checkout canceled" };

export default function CanceledPage() {
  return (
    <main className="max-w-2xl mx-auto px-4 py-24 text-center">
      <h1 className="text-3xl font-bold">Checkout canceled.</h1>
      <p className="mt-4 text-gray-600">No charge was made. Come back anytime.</p>
      <p className="mt-12">
        <a href="/" className="text-sm underline text-gray-600">Back to pricing</a>
      </p>
    </main>
  );
}
