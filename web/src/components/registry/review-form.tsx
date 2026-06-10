// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: AGPL-3.0-only

import { useEffect, useState } from "react";
import { Star, Loader2, Pencil, Trash2, EyeOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import {
  useSubmitFeedback,
  useMyFeedback,
  useUpdateFeedback,
  useDeleteFeedback,
} from "@/hooks/use-insights-api";

interface ReviewFormProps {
  listingId: string;
  listingType?: string;
  onSuccess?: () => void;
}

export function ReviewForm({
  listingId,
  listingType = "agent",
  onSuccess,
}: ReviewFormProps) {
  const [rating, setRating] = useState(0);
  const [hoveredStar, setHoveredStar] = useState(0);
  const [comment, setComment] = useState("");
  const [anonymous, setAnonymous] = useState(false);
  const [isEditing, setIsEditing] = useState(false);

  const { data: myReview, isError: noExistingReview } = useMyFeedback(
    listingType,
    listingId,
  );
  const submitMutation = useSubmitFeedback();
  const updateMutation = useUpdateFeedback();
  const deleteMutation = useDeleteFeedback();

  const hasExistingReview = !!myReview && !noExistingReview;

  // Populate form when editing existing review
  useEffect(() => {
    if (isEditing && myReview) {
      setRating(myReview.rating);
      setComment(myReview.comment ?? "");
      setAnonymous(myReview.anonymous ?? false);
    }
  }, [isEditing, myReview]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (rating === 0) return;

    if (isEditing && myReview) {
      updateMutation.mutate(
        {
          feedbackId: myReview.id,
          rating,
          comment: comment.trim() || undefined,
          anonymous,
        },
        {
          onSuccess: () => {
            setIsEditing(false);
            onSuccess?.();
          },
        },
      );
    } else {
      submitMutation.mutate(
        {
          listing_type: listingType,
          listing_id: listingId,
          rating,
          comment: comment.trim() || undefined,
          anonymous,
        },
        {
          onSuccess: () => {
            setRating(0);
            setComment("");
            setAnonymous(false);
            onSuccess?.();
          },
        },
      );
    }
  }

  function handleDelete() {
    if (!myReview) return;
    deleteMutation.mutate(myReview.id, {
      onSuccess: () => {
        setRating(0);
        setComment("");
        setAnonymous(false);
        setIsEditing(false);
        onSuccess?.();
      },
    });
  }

  function handleCancelEdit() {
    setIsEditing(false);
    setRating(0);
    setComment("");
    setAnonymous(false);
  }

  // If user already has a review and is not editing, show their review with edit/delete
  if (hasExistingReview && !isEditing) {
    return (
      <div className="space-y-3">
        <h4 className="text-sm font-semibold font-[family-name:var(--font-display)]">
          Your Review
        </h4>
        <div className="rounded-md border border-primary/30 bg-primary/5 p-4 space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1">
              {[1, 2, 3, 4, 5].map((star) => (
                <Star
                  key={star}
                  className={`h-4 w-4 ${
                    star <= myReview.rating
                      ? "fill-current text-amber-500"
                      : "text-muted-foreground/30"
                  }`}
                />
              ))}
            </div>
            <div className="flex items-center gap-2">
              {myReview.anonymous && (
                <span className="flex items-center gap-1 text-xs text-muted-foreground">
                  <EyeOff className="h-3 w-3" />
                  Anonymous
                </span>
              )}
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={() => setIsEditing(true)}
                title="Edit review"
              >
                <Pencil className="h-3.5 w-3.5" />
              </Button>
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 text-destructive hover:text-destructive"
                    disabled={deleteMutation.isPending}
                    title="Delete review"
                  >
                    {deleteMutation.isPending ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Trash2 className="h-3.5 w-3.5" />
                    )}
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Delete review?</AlertDialogTitle>
                    <AlertDialogDescription>
                      This will permanently remove your review. You can submit a new one afterwards.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                    <AlertDialogAction onClick={handleDelete}>
                      Delete
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </div>
          </div>
          {myReview.comment && (
            <p className="text-sm text-muted-foreground leading-relaxed">
              {myReview.comment}
            </p>
          )}
          <span className="text-xs text-muted-foreground">
            {myReview.created_at &&
              new Date(myReview.created_at).toLocaleDateString()}
            {myReview.updated_at && " (edited)"}
          </span>
        </div>
      </div>
    );
  }

  // Show the form (create or edit mode)
  const isPending = submitMutation.isPending || updateMutation.isPending;

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <h4 className="text-sm font-semibold font-[family-name:var(--font-display)]">
        {isEditing ? "Edit Your Review" : "Leave a Review"}
      </h4>

      <div className="flex items-center gap-1">
        {[1, 2, 3, 4, 5].map((star) => {
          const filled = star <= (hoveredStar || rating);
          return (
            <button
              key={star}
              type="button"
              className="p-0.5 transition-colors"
              onClick={() => setRating(star)}
              onMouseEnter={() => setHoveredStar(star)}
              onMouseLeave={() => setHoveredStar(0)}
            >
              <Star
                className={
                  filled
                    ? "h-5 w-5 fill-current text-amber-500"
                    : "h-5 w-5 text-muted-foreground"
                }
              />
            </button>
          );
        })}
      </div>

      <Textarea
        placeholder="Optional comment"
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        rows={3}
        className="resize-none"
      />

      <div className="flex items-center space-x-2">
        <Checkbox
          id="anonymous-review"
          checked={anonymous}
          onCheckedChange={(checked) => setAnonymous(checked === true)}
        />
        <Label
          htmlFor="anonymous-review"
          className="text-sm text-muted-foreground cursor-pointer"
        >
          Submit anonymously
        </Label>
      </div>

      <div className="flex items-center gap-2">
        <Button
          type="submit"
          size="sm"
          disabled={rating === 0 || isPending}
        >
          {isPending ? (
            <>
              <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
              {isEditing ? "Updating" : "Submitting"}
            </>
          ) : isEditing ? (
            "Update Review"
          ) : (
            "Submit Review"
          )}
        </Button>
        {isEditing && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={handleCancelEdit}
          >
            Cancel
          </Button>
        )}
      </div>
    </form>
  );
}
