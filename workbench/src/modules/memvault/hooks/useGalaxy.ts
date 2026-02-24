import { useMemo } from "react";
import type { MemoryBlock } from "@/types";
import type { GalaxyNode, GalaxyLink } from "../types";

export function useGalaxy(blocks: MemoryBlock[]) {
  const nodes: GalaxyNode[] = useMemo(
    () =>
      blocks.map((b) => ({
        id: b.id,
        label: b.content.slice(0, 40),
        type: b.block_type,
        confidence: b.confidence,
      })),
    [blocks],
  );

  const links: GalaxyLink[] = useMemo(() => {
    const result: GalaxyLink[] = [];
    for (let i = 0; i < blocks.length; i++) {
      for (let j = i + 1; j < blocks.length; j++) {
        const shared = blocks[i].tags.filter((t) => blocks[j].tags.includes(t));
        if (shared.length > 0) {
          result.push({
            source: blocks[i].id,
            target: blocks[j].id,
            strength: shared.length / Math.max(blocks[i].tags.length, blocks[j].tags.length, 1),
          });
        }
      }
    }
    return result;
  }, [blocks]);

  return { nodes, links };
}
