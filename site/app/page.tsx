import { PricingCard } from "@/components/PricingCard";
import { TIERS } from "@/lib/tiers";

export default function Home() {
  return (
    <main className="max-w-6xl mx-auto px-4 py-16">
      <section className="text-center mb-12">
        <h1 className="text-4xl md:text-5xl font-bold tracking-tight">AetherCloud</h1>
        <p className="mt-4 text-lg text-gray-600 max-w-2xl mx-auto">
          Autonomous agents that match your voice, connect to your tools, and ship work while you sleep.
        </p>
      </section>

      <section>
        <h2 className="text-2xl font-semibold mb-6 text-center">Choose a plan</h2>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {TIERS.map((tier) => <PricingCard key={tier.key} tier={tier} />)}
        </div>
      </section>

      <footer className="mt-16 text-center text-sm text-gray-500">
        Questions? <a href="mailto:support@aethersystems.net" className="underline">Email us</a>.
      </footer>
    </main>
  );
}
