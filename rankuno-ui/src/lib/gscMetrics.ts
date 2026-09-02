import type { FullPageIntelligenceProfile } from "../types/schema";

/** Calculates opportunity score for a page. */
export interface OpportunityScore {
  score: number;
  reason: string;
  category: "high" | "medium" | "low" | "none";
}

/** Formats GSC metrics for display. */
export const GscMetricsFormatter = {
  position(pos: number | null): string {
    if (pos === null) return "—";
    if (pos > 100) return "Beyond top 100";
    return pos.toFixed(1);
  },

  ctr(ctr: number | null): string {
    if (ctr === null) return "—";
    return `${(ctr * 100).toFixed(2)}%`;
  },

  positionColor(pos: number | null): "green" | "yellow" | "orange" | "red" | "gray" {
    if (pos === null) return "gray";
    if (pos <= 3) return "green";
    if (pos <= 10) return "yellow";
    if (pos <= 20) return "orange";
    return "red";
  },

  ctrColor(ctr: number | null, pos: number | null): "green" | "yellow" | "red" | "gray" {
    if (ctr === null) return "gray";
    if (pos !== null && pos <= 3 && ctr < 0.6) return "yellow"; // Top 3 but low CTR
    if (pos !== null && pos <= 10 && ctr < 0.1) return "yellow"; // Top 10 but low CTR
    if (ctr > 0.03) return "green";
    if (ctr > 0.01) return "yellow";
    return "red";
  },

  positionLabel(pos: number | null): string {
    if (pos === null) return "Not ranked";
    if (pos > 100) return "Below top 100";
    if (pos <= 3) return "Top 3";
    if (pos <= 10) return "Top 10";
    if (pos <= 20) return "Top 20";
    return `Position ${pos.toFixed(0)}`;
  },
};

/** Calculates opportunity score based on GSC metrics. */
export function calculateOpportunityScore(page: FullPageIntelligenceProfile): OpportunityScore {
  const { gsc_clicks, gsc_impressions, gsc_avg_position, gsc_ctr } = page;

  // No GSC data
  if (
    gsc_clicks === null ||
    gsc_impressions === null ||
    gsc_avg_position === null ||
    gsc_ctr === null
  ) {
    return { score: 0, reason: "No GSC data available", category: "none" };
  }

  // Not indexed
  if (gsc_impressions === 0) {
    return { score: 0, reason: "Not indexed in GSC", category: "none" };
  }

  // No clicks despite impressions (low CTR)
  if (gsc_clicks === 0 && gsc_impressions > 0) {
    const missedOpportunity = gsc_impressions * 0.01; // 1% CTR would be 1% of impressions
    return {
      score: missedOpportunity,
      reason: `${gsc_impressions.toLocaleString()} impressions with 0 clicks`,
      category: gsc_impressions > 100 ? "high" : "medium",
    };
  }

  // High impressions, low CTR, improvable position (opportunity to fix ranking)
  if (gsc_impressions > 10 && gsc_ctr < 0.01 && gsc_avg_position > 10) {
    const opportunityScore = gsc_impressions * (1 - gsc_ctr) * (1 / (gsc_avg_position / 10));
    return {
      score: opportunityScore,
      reason: `Position ${gsc_avg_position.toFixed(0)} with low CTR`,
      category: "high",
    };
  }

  // Already high-performing
  if (gsc_avg_position <= 3 && gsc_ctr > 0.03) {
    return { score: 0, reason: "Top performer", category: "none" };
  }

  // Moderate opportunity
  const score = Math.max(
    0,
    (gsc_impressions * (1 - gsc_ctr) * (Math.max(0, 20 - gsc_avg_position))) / 100,
  );

  return {
    score,
    reason: score > 0 ? `Position ${gsc_avg_position.toFixed(0)}, CTR ${(gsc_ctr * 100).toFixed(2)}%` : "Low opportunity",
    category: score > 100 ? "high" : score > 10 ? "medium" : "low",
  };
}

/** Filters pages by GSC metrics. */
export function filterPagesByGscMetrics(
  pages: FullPageIntelligenceProfile[],
  filters: {
    hasGscData?: boolean;
    minPosition?: number;
    maxPosition?: number;
    minCtr?: number;
    maxCtr?: number;
  },
): FullPageIntelligenceProfile[] {
  return pages.filter((page) => {
    // Filter: has GSC data
    if (filters.hasGscData === true) {
      if (page.gsc_clicks === null || page.gsc_impressions === null) {
        return false;
      }
    }

    // Filter: position range
    if (page.gsc_avg_position !== null) {
      if (filters.minPosition !== undefined && page.gsc_avg_position < filters.minPosition) {
        return false;
      }
      if (filters.maxPosition !== undefined && page.gsc_avg_position > filters.maxPosition) {
        return false;
      }
    }

    // Filter: CTR range
    if (page.gsc_ctr !== null) {
      if (filters.minCtr !== undefined && page.gsc_ctr < filters.minCtr) {
        return false;
      }
      if (filters.maxCtr !== undefined && page.gsc_ctr > filters.maxCtr) {
        return false;
      }
    }

    return true;
  });
}

/** Calculates site-wide GSC metrics. */
export function calculateSiteMetrics(pages: FullPageIntelligenceProfile[]) {
  const pagesWithData = pages.filter((p) => p.gsc_clicks !== null && p.gsc_impressions !== null);

  if (pagesWithData.length === 0) {
    return {
      totalClicks: 0,
      totalImpressions: 0,
      avgPosition: null,
      avgCtr: 0,
      coverage: 0,
      indexed: 0,
      notIndexed: pages.length,
    };
  }

  let totalClicks = 0;
  let totalImpressions = 0;
  let positionSum = 0;
  let positionCount = 0;
  let indexed = 0;

  for (const page of pagesWithData) {
    totalClicks += page.gsc_clicks ?? 0;
    totalImpressions += page.gsc_impressions ?? 0;
    if (page.gsc_avg_position !== null && page.gsc_avg_position > 0) {
      positionSum += page.gsc_avg_position;
      positionCount++;
    }
    if ((page.gsc_impressions ?? 0) > 0) {
      indexed++;
    }
  }

  const avgPosition = positionCount > 0 ? positionSum / positionCount : null;
  const avgCtr = totalImpressions > 0 ? totalClicks / totalImpressions : 0;
  const coverage = (pagesWithData.length / pages.length) * 100;

  return {
    totalClicks,
    totalImpressions,
    avgPosition,
    avgCtr,
    coverage,
    indexed,
    notIndexed: pages.length - indexed,
  };
}

/** Finds top opportunities by score. */
export function findTopOpportunities(
  pages: FullPageIntelligenceProfile[],
  limit = 10,
): Array<{ page: FullPageIntelligenceProfile; score: OpportunityScore }> {
  return pages
    .map((page) => ({
      page,
      score: calculateOpportunityScore(page),
    }))
    .filter((item) => item.score.category !== "none")
    .sort((a, b) => b.score.score - a.score.score)
    .slice(0, limit);
}
