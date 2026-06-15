// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { createContext, useContext, useState, useCallback, type ReactNode } from "react";
import { useHelpMode } from "@/hooks/use-help-mode";
import { HelpPanel } from "@/components/wiki/help-panel";
import type { DocRef } from "@/lib/docs-map";
import { SETTING_DOCS, SECTION_DOCS, PAGE_DOCS } from "@/lib/docs-map";

interface HelpContextValue {
	/** Whether modifier key is currently held */
	helpActive: boolean;
	/** Open the help panel for a setting key, section title, or page context */
	openHelp: (opts: { settingKey?: string; sectionTitle?: string; pageKey?: string; docRef?: DocRef }) => boolean;
	/** Whether the help panel is currently open */
	panelOpen: boolean;
}

const HelpContext = createContext<HelpContextValue>({
	helpActive: false,
	openHelp: () => false,
	panelOpen: false,
});

export function useHelp() {
	return useContext(HelpContext);
}

/**
 * Provides help mode context and renders the HelpPanel.
 * Wrap any page that should support modifier+click docs with this.
 */
export function HelpProvider({ children }: { children: ReactNode }) {
	const helpActive = useHelpMode();
	const [helpFile, setHelpFile] = useState<string | null>(null);
	const [helpAnchor, setHelpAnchor] = useState<string | undefined>();
	const [helpTitle, setHelpTitle] = useState<string | undefined>();

	const openHelp = useCallback(
		(opts: { settingKey?: string; sectionTitle?: string; pageKey?: string; docRef?: DocRef }) => {
			const ref =
				opts.docRef ||
				(opts.settingKey ? SETTING_DOCS[opts.settingKey] : undefined) ||
				(opts.sectionTitle ? SECTION_DOCS[opts.sectionTitle] : undefined) ||
				(opts.pageKey ? PAGE_DOCS[opts.pageKey] : undefined);
			if (!ref) return false;
			setHelpFile(ref.file);
			setHelpAnchor(ref.anchor);
			setHelpTitle(ref.label);
			return true;
		},
		[],
	);

	const panelOpen = helpFile !== null;

	return (
		<HelpContext.Provider value={{ helpActive, openHelp, panelOpen }}>
			{children}
			<HelpPanel
				file={helpFile}
				anchor={helpAnchor}
				title={helpTitle}
				onClose={() => {
					setHelpFile(null);
					setHelpAnchor(undefined);
					setHelpTitle(undefined);
				}}
			/>
			{helpActive && !panelOpen && (
				<div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 rounded-full bg-primary/90 text-primary-foreground px-4 py-1.5 text-xs font-medium shadow-lg animate-in fade-in slide-in-from-bottom-2">
					Click any highlighted element for docs
				</div>
			)}
		</HelpContext.Provider>
	);
}
