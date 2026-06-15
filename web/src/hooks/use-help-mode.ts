// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { useState, useEffect, useCallback } from "react";

/**
 * Hook that tracks whether the user is holding the help-mode modifier key
 * (Ctrl on Windows/Linux, Cmd on macOS). When active, interactive elements
 * with doc references should highlight as clickable help targets.
 */
export function useHelpMode() {
	const [active, setActive] = useState(false);

	const handleKeyDown = useCallback((e: KeyboardEvent) => {
		// Activate on Ctrl (Win/Linux) or Meta/Cmd (macOS)
		if (e.key === "Control" || e.key === "Meta") {
			setActive(true);
		}
	}, []);

	const handleKeyUp = useCallback((e: KeyboardEvent) => {
		if (e.key === "Control" || e.key === "Meta") {
			setActive(false);
		}
	}, []);

	const handleBlur = useCallback(() => {
		// Deactivate if user switches away from the window
		setActive(false);
	}, []);

	useEffect(() => {
		document.addEventListener("keydown", handleKeyDown);
		document.addEventListener("keyup", handleKeyUp);
		window.addEventListener("blur", handleBlur);
		return () => {
			document.removeEventListener("keydown", handleKeyDown);
			document.removeEventListener("keyup", handleKeyUp);
			window.removeEventListener("blur", handleBlur);
		};
	}, [handleKeyDown, handleKeyUp, handleBlur]);

	return active;
}
