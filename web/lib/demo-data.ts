export type Project = {
  id: string;
  name: string;
  description: string;
  papers: number;
  chunks: number;
  updatedAt: string;
};

export type SourceState = "ready" | "embedding" | "new" | "failed";

export type SourceFile = {
  id: string;
  name: string;
  pages: number;
  chunks?: number;
  state: SourceState;
  progress?: number;
};

export type SourceRef = {
  id: string;
  file: string;
  page: number;
  score: number;
  snippet: string;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: SourceRef[];
};

export const projects: Project[] = [
  {
    id: "zirconium",
    name: "Zirconium Alloys",
    description: "Corrosion, hydrogen pickup, and irradiation behavior in reactor materials.",
    papers: 12,
    chunks: 1840,
    updatedAt: "Today, 14:32",
  },
  {
    id: "batteries",
    name: "Solid-State Batteries",
    description: "Electrolytes, interfaces, and dendrite suppression literature review.",
    papers: 8,
    chunks: 973,
    updatedAt: "Yesterday",
  },
  {
    id: "catalysis",
    name: "CO₂ Catalysis",
    description: "Copper-based catalysts and selectivity mechanisms.",
    papers: 21,
    chunks: 3124,
    updatedAt: "Nov 8, 2026",
  },
];

export const demoSources: SourceFile[] = [
  { id: "s1", name: "Smith_2024_Hydrogen_Zr.pdf", pages: 14, chunks: 42, state: "ready" },
  { id: "s2", name: "Jones_2023_Corrosion_Review.pdf", pages: 28, chunks: 86, state: "ready" },
  { id: "s3", name: "Lee_2025_Irradiation_Effects.pdf", pages: 11, chunks: 31, state: "ready" },
  { id: "s4", name: "Patel_2026_Oxide_Layers.pdf", pages: 9, state: "embedding", progress: 62 },
  { id: "s5", name: "Wang_2022_Diffusion_Models.pdf", pages: 16, state: "new" },
  { id: "s6", name: "Corrupted_scan.pdf", pages: 4, state: "failed" },
];

export const demoMessages: ChatMessage[] = [
  {
    id: "m1",
    role: "user",
    content: "How does hydrogen affect zirconium alloy corrosion in reactor environments?",
  },
  {
    id: "m2",
    role: "assistant",
    content: `**Hydrogen pickup accelerates corrosion and embrittlement** in zirconium alloys under reactor conditions.

- **Diffusion & hydrides:** Absorbed hydrogen diffuses into the metal matrix and precipitates as brittle zirconium hydrides, reducing ductility and fracture toughness. [Smith_2024_Hydrogen_Zr.pdf, p. 4]
- **Oxide layer effects:** Higher hydrogen content is associated with faster oxide growth and earlier transition behavior in the protective oxide film. [Jones_2023_Corrosion_Review.pdf, p. 12]
- **Irradiation coupling:** Irradiation can modify hydrogen transport and trapping, which changes local pickup rates and embrittlement risk. [Lee_2025_Irradiation_Effects.pdf, p. 7]

Overall, the sources indicate hydrogen is both a corrosion byproduct and a driver of mechanical degradation, so managing pickup is critical for cladding lifetime.`,
    sources: [
      {
        id: "r1",
        file: "Smith_2024_Hydrogen_Zr.pdf",
        page: 4,
        score: 0.94,
        snippet:
          "Hydrogen absorbed during aqueous corrosion diffuses inward and precipitates as δ-hydrides, which act as crack initiation sites under tensile loading.",
      },
      {
        id: "r2",
        file: "Jones_2023_Corrosion_Review.pdf",
        page: 12,
        score: 0.89,
        snippet:
          "Alloys exhibiting higher hydrogen pickup fractions show accelerated post-transition oxide kinetics and reduced corrosion margin.",
      },
      {
        id: "r3",
        file: "Lee_2025_Irradiation_Effects.pdf",
        page: 7,
        score: 0.84,
        snippet:
          "Neutron irradiation introduces defect traps that alter hydrogen mobility, leading to heterogeneous hydride distributions near the metal–oxide interface.",
      },
    ],
  },
];
