// SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
//
// SPDX-License-Identifier: AGPL-3.0-only

"use client";

import { PageHeader } from "@/components/layouts/page-header";
import { SpecDagEditor } from "@/components/eval/spec-dag-editor";
import { SpecDagList } from "@/components/eval/spec-dag-list";

export default function SpecDagsPage() {
  return (
    <>
      <PageHeader
        title="Spec DAGs"
        breadcrumbs={[
          { label: "Eval", href: "/eval" },
          { label: "Spec DAGs" },
        ]}
      />
      <div className="px-4 py-4 grid grid-cols-1 xl:grid-cols-[1fr_320px] gap-4 min-h-[calc(100vh-7rem)]">
        <SpecDagEditor />
        <SpecDagList />
      </div>
    </>
  );
}
