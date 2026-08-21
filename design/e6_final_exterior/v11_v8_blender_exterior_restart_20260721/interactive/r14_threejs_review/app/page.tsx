import type { Metadata } from "next";
import { R14Client } from "./r14-client";

export const metadata: Metadata = {
  title: "WorkCore E6 · R14 Interactive Review",
  description:
    "R14 visual endpoints, interaction previews and E6-DFR3 historical packaging reference; not an engineering or production release.",
};

export default function Home() {
  return <R14Client />;
}
