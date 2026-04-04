"use client";

import Link from "next/link";
import { DashboardCard } from "@/components/dashboard/dashboard-card";
import { BarList } from "@/components/dashboard/bar-list";
import { NoData } from "@/components/dashboard/no-data";
import { compactNumber } from "@/lib/utils";

interface TopItem {
  id: string;
  name: string;
  value: number;
}

interface TopItemsCardProps {
  title: string;
  data: TopItem[] | undefined;
  isLoading: boolean;
  linkPrefix: string;
  className?: string;
}

export function TopItemsCard({ title, data, isLoading, linkPrefix, className }: TopItemsCardProps) {
  return (
    <DashboardCard title={title} isLoading={isLoading} className={className}>
      {!data?.length && !isLoading ? (
        <NoData description="Data will appear once activity is recorded." />
      ) : (
        <BarList
          data={(data ?? []).map((item) => ({
            name: (
              <Link
                href={`${linkPrefix}${item.id}`}
                className="hover:underline"
              >
                {item.name}
              </Link>
            ),
            value: item.value,
          }))}
          valueFormatter={compactNumber}
        />
      )}
    </DashboardCard>
  );
}
