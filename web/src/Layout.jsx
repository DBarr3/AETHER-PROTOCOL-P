import React, { useEffect } from "react";
import { Outlet, useLocation } from "react-router-dom";
import SiteNavbar from "./components/SiteNavbar.jsx";
import SiteAtmosphere from "./components/SiteAtmosphere.jsx";
import SpinningGlobe from "./components/SpinningGlobe.jsx";
import { Footer5 } from "./pages/home/components/Footer5.jsx";

export default function Layout() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);

  const isHome = pathname === "/";

  return (
    <>
      {isHome && <SpinningGlobe />}
      <div className={`relative z-10 min-h-screen text-aether-text ${isHome ? "" : "bg-aether-bg"}`}>
        {!isHome && <SiteAtmosphere />}
        <SiteNavbar />
        <main className="relative">
          <Outlet />
        </main>
        <Footer5 />
      </div>
    </>
  );
}
