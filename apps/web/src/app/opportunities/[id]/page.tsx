"use client";

/**
 * Opportunity detail — the full evidence view for one detected signal.
 * Shows the normalised definition, odds timeline, de-vig method, friction/costs,
 * model probability with uncertainty, injuries/lineups, and every warning.
 */

import { useParams } from "next/navigation";

import {
  BulletList,
  ErrorBlock,
  KeyValueList,
  LoadingBlock,
  SectionPanel,
} from "@/components/StateBlocks";
import {
  frictionRows,
  marketDefinitionRows,
  opportunityEventLabel,
  opportunityMarketLabel,
  predictionForOutcome,
  predictionExplanationLines,
  toLegViews,
} from "@/lib/derive";
import {
  formatBps,
  formatProbability,
  formatRatioPercent,
  formatUtcTimestamp,
} from "@/lib/format";
import { useMarkets, useOpportunity, usePredictions } from "@/lib/queries";

export default function OpportunityDetailPage() {
  const params = useParams();
  const opportunityId = typeof params.id === "string" ? params.id : "";

  const opportunityQuery = useOpportunity(opportunityId, { enabled: opportunityId !== "" });
  const marketsQuery = useMarkets({ eventId: undefined, marketId: opportunityId });
  const predictionsQuery = usePredictions(undefined, {});

  if (!opportunityId) {
    return (
      <ErrorBlock
        error={{
          kind: "unknown",
          status: null,
          message: "No opportunity id provided.",
          detail: null,
          url: "/v1/opportunities",
          method: "GET",
          retriable: false,
        }}
      />
    );
  }
  if (opportunityQuery.isPending) {
    return <LoadingBlock label="Loading opportunity detail" />;
  }
  if (opportunityQuery.isError || opportunityQuery.data === undefined) {
    return (
      <ErrorBlock
        error={{
          kind: "unknown",
          status: null,
          message:
            opportunityQuery.error instanceof Error
              ? opportunityQuery.error.message
              : "Unknown error",
          detail: null,
          url: `/v1/opportunities/${opportunityId}`,
          method: "GET",
          retriable: true,
        }}
        onRetry={() => void opportunityQuery.refetch()}
      />
    );
  }
  const result = opportunityQuery.data;
  if (!result.ok) {
    return <ErrorBlock error={result.error} onRetry={() => void opportunityQuery.refetch()} />;
  }

  const opportunity = result.data;
  const legs = toLegViews(opportunity.best_legs);
  const costs = frictionRows(opportunity.friction);
  const marketRow = marketsQuery.data?.ok
    ? marketsQuery.data.data.items.find((m) => m.id === opportunity.market_id) ?? null
    : null;
  const definitionRows = marketDefinitionRows(marketRow, opportunity.market_id);
  const predictions = predictionsQuery.data?.ok ? predictionsQuery.data.data.items : [];
  const prediction = predictionForOutcome(
    predictions,
    opportunity.market_type,
    legs[0]?.outcomeLabel ?? "",
  );
