// SPDX-FileCopyrightText: 2026 Shree Harini <shree@observal.dev>
// SPDX-License-Identifier: Apache-2.0

/**
 * File tree component for skill folder authoring and review.
 *
 * Displays a hierarchical view of files in a skill folder with support for:
 * - Adding/removing files
 * - Toggling executable mode
 * - Viewing file sizes
 * - Selecting files for editing
 */

import { useState, useMemo, useCallback } from "react";
import {
	ChevronDown,
	ChevronRight,
	File,
	FileCode,
	FileText,
	Folder,
	FolderOpen,
	Image,
	MoreVertical,
	Plus,
	Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuSeparator,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

import { cn } from "@/lib/utils";
import type { SkillResource, SkillManifestFile } from "@/lib/types";

// ── Types ───────────────────────────────────────────────────────────

interface FileNode {
	name: string;
	path: string;
	type: "file" | "directory";
	children?: FileNode[];
	file?: SkillResource | SkillManifestFile;
	size?: number;
	executable?: boolean;
}

interface SkillFileTreeProps {
	/** Files to display (authoring mode) */
	files?: SkillResource[];
	/** Manifest files to display (review/read-only mode) */
	manifest?: SkillManifestFile[];
	/** Currently selected file path */
	selectedPath?: string;
	/** Called when a file is selected */
	onSelectFile?: (path: string) => void;
	/** Called when a file should be deleted */
	onDeleteFile?: (path: string) => void;
	/** Called when a file's executable mode should be toggled */
	onToggleExecutable?: (path: string) => void;
	/** Called when add file is requested */
	onAddFile?: (parentPath: string) => void;
	/** Whether the tree is read-only */
	readOnly?: boolean;
	/** Custom class name */
	className?: string;
}

// ── Helpers ─────────────────────────────────────────────────────────

function getFileIcon(name: string, executable?: boolean) {
	const ext = name.split(".").pop()?.toLowerCase() || "";

	if (executable || ["sh", "bash", "py", "rb", "js", "mjs"].includes(ext)) {
		return FileCode;
	}
	if (["png", "jpg", "jpeg", "gif", "svg", "webp", "ico"].includes(ext)) {
		return Image;
	}
	if (["md", "txt", "json", "yaml", "yml", "toml"].includes(ext)) {
		return FileText;
	}
	return File;
}

function formatSize(bytes: number): string {
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
	return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function buildFileTree(files: Array<SkillResource | SkillManifestFile>): FileNode[] {
	const root: FileNode[] = [];
	const dirs = new Map<string, FileNode>();

	// Sort files by path
	const sorted = [...files].sort((a, b) => a.path.localeCompare(b.path));

	for (const file of sorted) {
		const parts = file.path.split("/");
		const fileName = parts.pop()!;
		let parent = root;

		// Create directory nodes as needed
		let currentPath = "";
		for (const part of parts) {
			currentPath = currentPath ? `${currentPath}/${part}` : part;
			let dir = dirs.get(currentPath);
			if (!dir) {
				dir = {
					name: part,
					path: currentPath,
					type: "directory",
					children: [],
				};
				dirs.set(currentPath, dir);
				parent.push(dir);
			}
			parent = dir.children!;
		}

		// Add file node
		const fileNode: FileNode = {
			name: fileName,
			path: file.path,
			type: "file",
			file,
			size: "size" in file ? file.size : file.content.length,
			executable: "executable" in file ? file.executable : ("mode" in file ? file.mode === "0755" : false),
		};
		parent.push(fileNode);
	}

	return root;
}

// ── Components ──────────────────────────────────────────────────────

interface TreeNodeProps {
	node: FileNode;
	level: number;
	selectedPath?: string;
	onSelect?: (path: string) => void;
	onDelete?: (path: string) => void;
	onToggleExecutable?: (path: string) => void;
	onAddFile?: (parentPath: string) => void;
	readOnly?: boolean;
}

function TreeNode({
	node,
	level,
	selectedPath,
	onSelect,
	onDelete,
	onToggleExecutable,
	onAddFile,
	readOnly,
}: TreeNodeProps) {
	const [expanded, setExpanded] = useState(level < 2);
	const isSelected = selectedPath === node.path;
	const isSkillMd = node.name === "SKILL.md";

	const handleClick = useCallback(() => {
		if (node.type === "directory") {
			setExpanded(!expanded);
		} else {
			onSelect?.(node.path);
		}
	}, [node, expanded, onSelect]);

	const FileIcon = node.type === "directory"
		? (expanded ? FolderOpen : Folder)
		: getFileIcon(node.name, node.executable);

	const content = (
		<div
			className={cn(
				"flex items-center gap-1.5 py-1 px-2 rounded-sm cursor-pointer text-sm flex-1",
				"hover:bg-muted/50 transition-colors",
				isSelected && "bg-primary/10 text-primary",
			)}
			style={{ paddingLeft: `${level * 16 + 8}px` }}
			onClick={handleClick}
		>
			{node.type === "directory" && (
				<span className="w-4 h-4 flex items-center justify-center">
					{expanded ? (
						<ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
					) : (
						<ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
					)}
				</span>
			)}
			{node.type === "file" && <span className="w-4" />}
			<FileIcon className={cn(
				"h-4 w-4 shrink-0",
				node.type === "directory" ? "text-amber-500" : "text-muted-foreground",
				node.executable && "text-green-600",
			)} />
			<span className="truncate flex-1">{node.name}</span>
			{node.executable && !isSkillMd && (
				<Badge variant="outline" className="text-[10px] px-1 py-0 h-4">
					exec
				</Badge>
			)}
			{node.size !== undefined && (
				<span className="text-xs text-muted-foreground">
					{formatSize(node.size)}
				</span>
			)}
		</div>
	);

	// Action menu for files/directories (non-readonly mode)
	const actionMenu = !readOnly && (node.type === "file" ? !isSkillMd : true) && (
		<DropdownMenu>
			<DropdownMenuTrigger asChild>
				<Button
					variant="ghost"
					size="icon"
					className="h-6 w-6 opacity-0 group-hover:opacity-100"
					onClick={(e) => e.stopPropagation()}
				>
					<MoreVertical className="h-3.5 w-3.5" />
				</Button>
			</DropdownMenuTrigger>
			<DropdownMenuContent align="end">
				{node.type === "file" && !isSkillMd && (
					<>
						<DropdownMenuItem onClick={() => onToggleExecutable?.(node.path)}>
							{node.executable ? "Remove executable" : "Make executable"}
						</DropdownMenuItem>
						<DropdownMenuSeparator />
						<DropdownMenuItem
							className="text-destructive"
							onClick={() => onDelete?.(node.path)}
						>
							<Trash2 className="h-4 w-4 mr-2" />
							Delete
						</DropdownMenuItem>
					</>
				)}
				{node.type === "directory" && (
					<DropdownMenuItem onClick={() => onAddFile?.(node.path)}>
						<Plus className="h-4 w-4 mr-2" />
						Add file
					</DropdownMenuItem>
				)}
			</DropdownMenuContent>
		</DropdownMenu>
	);

	const wrappedContent = (
		<div className="group flex items-center">
			{content}
			{actionMenu}
		</div>
	);

	return (
		<>
			{wrappedContent}
			{node.type === "directory" && expanded && node.children?.map((child) => (
				<TreeNode
					key={child.path}
					node={child}
					level={level + 1}
					selectedPath={selectedPath}
					onSelect={onSelect}
					onDelete={onDelete}
					onToggleExecutable={onToggleExecutable}
					onAddFile={onAddFile}
					readOnly={readOnly}
				/>
			))}
		</>
	);
}

// ── Main Component ──────────────────────────────────────────────────

export function SkillFileTree({
	files,
	manifest,
	selectedPath,
	onSelectFile,
	onDeleteFile,
	onToggleExecutable,
	onAddFile,
	readOnly = false,
	className,
}: SkillFileTreeProps) {
	const allFiles = useMemo(() => {
		if (manifest) return manifest;
		if (files) return files;
		return [];
	}, [files, manifest]);

	const tree = useMemo(() => buildFileTree(allFiles), [allFiles]);

	const totalSize = useMemo(() => {
		return allFiles.reduce((sum, f) => {
			const size = "size" in f ? f.size : f.content.length;
			return sum + size;
		}, 0);
	}, [allFiles]);

	if (allFiles.length === 0) {
		return (
			<div className={cn("flex flex-col items-center justify-center py-8 text-muted-foreground", className)}>
				<Folder className="h-12 w-12 mb-2 opacity-50" />
				<p className="text-sm">No files yet</p>
				{!readOnly && onAddFile && (
					<Button variant="outline" size="sm" className="mt-2" onClick={() => onAddFile("")}>
						<Plus className="h-4 w-4 mr-1" />
						Add file
					</Button>
				)}
			</div>
		);
	}

	return (
		<div className={cn("flex flex-col", className)}>
			<div className="flex items-center justify-between px-2 py-1 border-b text-xs text-muted-foreground">
				<span>{allFiles.length} files</span>
				<span>{formatSize(totalSize)}</span>
			</div>
			<div className="flex-1 overflow-auto py-1">
				{tree.map((node) => (
					<TreeNode
						key={node.path}
						node={node}
						level={0}
						selectedPath={selectedPath}
						onSelect={onSelectFile}
						onDelete={onDeleteFile}
						onToggleExecutable={onToggleExecutable}
						onAddFile={onAddFile}
						readOnly={readOnly}
					/>
				))}
			</div>
			{!readOnly && onAddFile && (
				<div className="border-t p-2">
					<Button variant="ghost" size="sm" className="w-full" onClick={() => onAddFile("")}>
						<Plus className="h-4 w-4 mr-1" />
						Add file
					</Button>
				</div>
			)}
		</div>
	);
}

export default SkillFileTree;
