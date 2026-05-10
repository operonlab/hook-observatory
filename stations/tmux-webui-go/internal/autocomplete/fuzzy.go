package autocomplete

import "strings"

// fuzzyScore returns a numeric match quality between query and text.
// Scoring mirrors the Python _fuzzy_score implementation:
//
//	>= 1000 : exact prefix match (1000 - len(text) for tie-breaking)
//	>= 500  : substring match   (500  - index of match for tie-breaking)
//	1..N    : subsequence match (number of matched characters)
//	-1      : no match
func fuzzyScore(query, text string) int {
	if query == "" {
		return 100
	}
	q := strings.ToLower(query)
	t := strings.ToLower(text)

	// Exact prefix match.
	if strings.HasPrefix(t, q) {
		return 1000 - len(t)
	}

	// Substring match.
	if idx := strings.Index(t, q); idx >= 0 {
		return 500 - idx
	}

	// Subsequence match: advance through query chars in order.
	qi := 0
	score := 0
	for _, ch := range t {
		if qi < len(q) && ch == rune(q[qi]) {
			qi++
			score++
		}
	}
	if qi == len(q) {
		return score
	}
	return -1
}

// rankAndFilter filters items whose fuzzy score against query is >= 0,
// sorts them by score descending, and returns the top maxResults.
// If query is empty, the original slice (up to maxResults) is returned as-is.
func rankAndFilter(items []Item, query string, maxResults int) []Item {
	if query == "" {
		if len(items) <= maxResults {
			return items
		}
		return items[:maxResults]
	}

	type scored struct {
		score int
		item  Item
	}

	results := make([]scored, 0, len(items))
	for _, it := range items {
		s := fuzzyScore(query, it.Name)
		if s >= 0 {
			results = append(results, scored{s, it})
		}
	}

	// Sort descending by score (insertion sort is fine for typical N < 200).
	for i := 1; i < len(results); i++ {
		for j := i; j > 0 && results[j].score > results[j-1].score; j-- {
			results[j], results[j-1] = results[j-1], results[j]
		}
	}

	limit := len(results)
	if limit > maxResults {
		limit = maxResults
	}
	out := make([]Item, limit)
	for i := range out {
		out[i] = results[i].item
	}
	return out
}
