import React, { lazy, Suspense } from "react";
import { Routes, Route } from "react-router-dom";
import Layout from "./Layout.jsx";

const Home = lazy(() => import("./pages/home/index.jsx"));
const ProtocolFamily = lazy(() => import("./pages/protocol-family/index.jsx"));
const AetherCloud = lazy(() => import("./pages/aether-cloud/index.jsx"));
const Contact = lazy(() => import("./pages/contact/index.jsx"));
const Pricing = lazy(() => import("./pages/pricing/index.jsx"));
const Demo = lazy(() => import("./pages/demo/index.jsx"));
const Documentation = lazy(() => import("./pages/documentation/index.jsx"));
const Blog = lazy(() => import("./pages/blog/index.jsx"));
const BlogPost = lazy(() => import("./pages/blog-post/index.jsx"));

export default function App() {
  return (
    <Suspense fallback={<div style={{ background: "#0a0a0f", minHeight: "100vh" }} />}>
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="protocol-family" element={<ProtocolFamily />} />
        <Route path="aether-cloud" element={<AetherCloud />} />
        <Route path="contact" element={<Contact />} />
        <Route path="pricing" element={<Pricing />} />
        <Route path="demo" element={<Demo />} />
        <Route path="documentation" element={<Documentation />} />
        <Route path="blog" element={<Blog />} />
        <Route path="blog-post" element={<BlogPost />} />
      </Route>
    </Routes>
    </Suspense>
  );
}
