import React from "react";

export default function SiteAtmosphere() {
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 -z-10 overflow-hidden"
      style={{
        background:
          "radial-gradient(ellipse 120% 80% at 50% -10%, #0a0c15 0%, #040507 62%)",
      }}
    >
      {/* Grid overlay */}
      <div
        className="absolute inset-0"
        style={{
          backgroundImage:
            "linear-gradient(rgba(0,212,255,0.035) 1px, transparent 1px), linear-gradient(90deg, rgba(0,212,255,0.035) 1px, transparent 1px)",
          backgroundSize: "48px 48px",
          maskImage:
            "radial-gradient(ellipse 80% 60% at 50% 30%, black 55%, transparent 100%)",
          WebkitMaskImage:
            "radial-gradient(ellipse 80% 60% at 50% 30%, black 55%, transparent 100%)",
        }}
      />

      {/* Glow spheres */}
      <div
        className="absolute"
        style={{
          top: "-10%",
          left: "-10%",
          width: "880px",
          height: "880px",
          borderRadius: "9999px",
          background:
            "radial-gradient(circle, rgba(0,212,255,0.22), rgba(0,212,255,0) 60%)",
          filter: "blur(140px)",
          opacity: 0.9,
          animation: "aether-drift-1 26s ease-in-out infinite",
        }}
      />
      <div
        className="absolute"
        style={{
          top: "20%",
          right: "-8%",
          width: "720px",
          height: "720px",
          borderRadius: "9999px",
          background:
            "radial-gradient(circle, rgba(212,160,23,0.14), rgba(212,160,23,0) 60%)",
          filter: "blur(150px)",
          opacity: 0.85,
          animation: "aether-drift-2 32s ease-in-out infinite",
        }}
      />
      <div
        className="absolute"
        style={{
          bottom: "-12%",
          left: "25%",
          width: "960px",
          height: "960px",
          borderRadius: "9999px",
          background:
            "radial-gradient(circle, rgba(232,64,64,0.10), rgba(232,64,64,0) 60%)",
          filter: "blur(160px)",
          opacity: 0.8,
          animation: "aether-drift-3 38s ease-in-out infinite",
        }}
      />

      {/* Vignette */}
      <div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse 120% 90% at 50% 50%, transparent 55%, rgba(4,5,7,0.85) 100%)",
        }}
      />

      {/* Noise */}
      <svg
        className="absolute inset-0 h-full w-full opacity-[0.035] mix-blend-overlay"
        xmlns="http://www.w3.org/2000/svg"
      >
        <filter id="aether-noise">
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.9"
            numOctaves="2"
            stitchTiles="stitch"
          />
          <feColorMatrix type="saturate" values="0" />
        </filter>
        <rect width="100%" height="100%" filter="url(#aether-noise)" />
      </svg>
    </div>
  );
}
