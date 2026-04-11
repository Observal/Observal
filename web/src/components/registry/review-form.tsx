"use client";

import { useState } from "react";
import { Star, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useSubmitFeedback } from "@/hooks/use-api";

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

  const mutation = useSubmitFeedback();

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (rating === 0) return;

    mutation.mutate(
      {
        listing_type: listingType,
        listing_id: listingId,
        stars: rating,
        comment: comment.trim() || undefined,
      },
      {
        onSuccess: () => {
          setRating(0);
          setComment("");
          onSuccess?.();
        },
      },
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <h4 className="text-sm font-semibold font-[family-name:var(--font-display)]">
        Leave a Review
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

      <Button
        type="submit"
        size="sm"
        disabled={rating === 0 || mutation.isPending}
      >
        {mutation.isPending ? (
          <>
            <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />
            Submitting
          </>
        ) : (
          "Submit Review"
        )}
      </Button>
    </form>
  );
}
