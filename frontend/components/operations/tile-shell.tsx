"use client";

import type { ReactNode } from "react";
import { RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * Shared shell for every operations tile (phase-04 §3): a `Card` with a
 * title, an optional click-through link, a manual refresh button (§6 "Manual
 * refresh button per tile"), and loading/error states so each tile
 * component only needs to own its own data + rendering.
 */
export function TileShell({
  title,
  description,
  href,
  isPending,
  isError,
  onRefresh,
  children,
}: {
  title: string;
  description?: string;
  href?: string;
  isPending: boolean;
  isError: boolean;
  onRefresh: () => void;
  children: ReactNode;
}) {
  return (
    <Card className="flex flex-col">
      <CardHeader className="flex-row items-start justify-between space-y-0 pb-2">
        <div>
          <CardTitle className="text-base">
            {href ? (
              <a href={href} className="hover:underline">
                {title}
              </a>
            ) : (
              title
            )}
          </CardTitle>
          {description && <CardDescription className="mt-1">{description}</CardDescription>}
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={`Refresh ${title}`}
          onClick={onRefresh}
          className="h-8 w-8"
        >
          <RefreshCw className={isPending ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
        </Button>
      </CardHeader>
      <CardContent className="flex-1">
        {isPending ? (
          <div className="space-y-2">
            <Skeleton className="h-6 w-1/2" />
            <Skeleton className="h-16 w-full" />
          </div>
        ) : isError ? (
          <p className="text-sm text-destructive">Failed to load.</p>
        ) : (
          children
        )}
      </CardContent>
    </Card>
  );
}
