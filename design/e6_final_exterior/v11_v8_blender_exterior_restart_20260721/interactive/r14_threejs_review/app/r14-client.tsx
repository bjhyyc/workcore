"use client";

import dynamic from "next/dynamic";

const R14Experience = dynamic(
  () => import("./r14-experience").then((module) => module.R14Experience),
  {
    ssr: false,
    loading: () => (
      <main className="review-shell" aria-busy="true">
        <div className="loading-plate">
          <span className="loading-aperture" />
          <span className="loading-copy">Loading review engine</span>
        </div>
      </main>
    ),
  },
);

export function R14Client() {
  return <R14Experience />;
}
