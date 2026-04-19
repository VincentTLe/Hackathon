/*
 * Guardian-Sleuth: C++ Bron-Kerbosch Maximal Clique Engine
 * ---------------------------------------------------------
 * Implements the Bron-Kerbosch algorithm with Tomita pivot selection
 * for enumerating all maximal cliques in an undirected graph.
 *
 * Exposed via pybind11:
 *   find_cliques(n_nodes, edge_list) -> List[List[int]]
 *
 * Build:
 *   python setup.py build_ext --inplace
 *
 * Reference: Tomita et al. (2006), "The worst-case time complexity for
 * generating all maximal cliques and computational experiments."
 * Theoretical Computer Science 363(1), 28-42.
 */

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <algorithm>
#include <unordered_set>
#include <vector>

namespace py = pybind11;

// --------------------------------------------------------------------------
// Adjacency representation
// --------------------------------------------------------------------------

using AdjList = std::vector<std::unordered_set<int>>;

static AdjList build_adj(int n, const std::vector<std::pair<int, int>>& edges) {
    AdjList adj(n);
    for (auto& [u, v] : edges) {
        if (u >= 0 && u < n && v >= 0 && v < n && u != v) {
            adj[u].insert(v);
            adj[v].insert(u);
        }
    }
    return adj;
}

// --------------------------------------------------------------------------
// Bron-Kerbosch with Tomita pivot (maximises |P ∩ N(u)|)
// --------------------------------------------------------------------------

static void bron_kerbosch(
    std::vector<int>& R,          // current clique being grown
    std::vector<int>  P,          // candidates that can extend R
    std::vector<int>  X,          // nodes already processed
    const AdjList&    adj,
    std::vector<std::vector<int>>& results,
    size_t max_cliques            // safety cap for huge graphs
) {
    if (results.size() >= max_cliques) return;

    if (P.empty() && X.empty()) {
        if (R.size() >= 2) results.push_back(R);   // only keep cliques ≥ 2
        return;
    }

    // Choose pivot u that maximises |P ∩ N(u)|  (Tomita selection)
    int pivot = -1;
    int best  = -1;
    for (int u : P) {
        int cnt = 0;
        for (int v : P) if (adj[u].count(v)) ++cnt;
        if (cnt > best) { best = cnt; pivot = u; }
    }
    for (int u : X) {
        int cnt = 0;
        for (int v : P) if (adj[u].count(v)) ++cnt;
        if (cnt > best) { best = cnt; pivot = u; }
    }

    // Iterate over P \ N(pivot)
    std::vector<int> candidates;
    for (int v : P) {
        if (pivot == -1 || !adj[pivot].count(v)) candidates.push_back(v);
    }

    for (int v : candidates) {
        // Build P' = P ∩ N(v)  and  X' = X ∩ N(v)
        std::vector<int> P_new, X_new;
        P_new.reserve(P.size());
        X_new.reserve(X.size());
        for (int u : P) if (adj[v].count(u)) P_new.push_back(u);
        for (int u : X) if (adj[v].count(u)) X_new.push_back(u);

        R.push_back(v);
        bron_kerbosch(R, std::move(P_new), std::move(X_new), adj, results, max_cliques);
        R.pop_back();

        // Move v from P to X
        P.erase(std::find(P.begin(), P.end(), v));
        X.push_back(v);
    }
}

// --------------------------------------------------------------------------
// Public API
// --------------------------------------------------------------------------

/**
 * find_cliques(n_nodes, edge_list, max_cliques=10000)
 *
 * Parameters
 * ----------
 * n_nodes    : int — total number of nodes (0 … n-1)
 * edge_list  : List[Tuple[int, int]] — undirected edges (duplicates ignored)
 * max_cliques: int — safety cap; stops early if this many cliques are found
 *
 * Returns
 * -------
 * List[List[int]] — each inner list is a maximal clique (node IDs, sorted)
 */
std::vector<std::vector<int>> find_cliques(
    int n,
    const std::vector<std::pair<int, int>>& edges,
    size_t max_cliques = 10000
) {
    if (n <= 0) return {};

    AdjList adj = build_adj(n, edges);

    // Initial P = all nodes that have at least one neighbour
    std::vector<int> P;
    P.reserve(n);
    for (int i = 0; i < n; ++i) {
        if (!adj[i].empty()) P.push_back(i);
    }

    std::vector<std::vector<int>> results;
    results.reserve(std::min((size_t)1024, max_cliques));

    std::vector<int> R, X;
    bron_kerbosch(R, P, X, adj, results, max_cliques);

    // Sort each clique and deduplicate
    for (auto& clique : results) std::sort(clique.begin(), clique.end());
    std::sort(results.begin(), results.end());
    results.erase(std::unique(results.begin(), results.end()), results.end());

    return results;
}

/**
 * find_cliques_windowed(n_nodes, edge_list, min_size=3, max_cliques=10000)
 *
 * Convenience wrapper that filters to cliques of at least `min_size` nodes.
 * Useful for AML: small cliques (≥3) are more indicative of fraud rings.
 */
std::vector<std::vector<int>> find_cliques_windowed(
    int n,
    const std::vector<std::pair<int, int>>& edges,
    int min_size    = 3,
    size_t max_cliques = 10000
) {
    auto all = find_cliques(n, edges, max_cliques);
    std::vector<std::vector<int>> filtered;
    filtered.reserve(all.size());
    for (auto& c : all) {
        if ((int)c.size() >= min_size) filtered.push_back(std::move(c));
    }
    return filtered;
}

// --------------------------------------------------------------------------
// pybind11 module definition
// --------------------------------------------------------------------------

PYBIND11_MODULE(clique_engine, m) {
    m.doc() = R"pbdoc(
        Guardian-Sleuth Clique Engine
        ==============================
        Fast C++ Bron-Kerbosch maximal clique detection with Tomita pivot
        selection, compiled as a Python extension via pybind11.

        Functions
        ---------
        find_cliques(n_nodes, edge_list, max_cliques=10000)
            Enumerate all maximal cliques in the graph.

        find_cliques_windowed(n_nodes, edge_list, min_size=3, max_cliques=10000)
            Same as find_cliques but filters to cliques of at least min_size.
    )pbdoc";

    m.def(
        "find_cliques",
        &find_cliques,
        py::arg("n_nodes"),
        py::arg("edge_list"),
        py::arg("max_cliques") = 10000,
        R"pbdoc(
            Find all maximal cliques in an undirected graph.

            Parameters
            ----------
            n_nodes : int
                Number of nodes (IDs must be in range [0, n_nodes)).
            edge_list : list of (int, int)
                Undirected edges. Duplicates and self-loops are ignored.
            max_cliques : int, optional
                Maximum number of cliques to return (safety cap).

            Returns
            -------
            list of list of int
                Each inner list is a maximal clique, nodes sorted ascending.
        )pbdoc"
    );

    m.def(
        "find_cliques_windowed",
        &find_cliques_windowed,
        py::arg("n_nodes"),
        py::arg("edge_list"),
        py::arg("min_size")    = 3,
        py::arg("max_cliques") = 10000,
        R"pbdoc(
            Find maximal cliques with at least min_size nodes.

            Useful for AML ring detection where isolated pairs are noise.
        )pbdoc"
    );
}
