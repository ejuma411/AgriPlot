document.addEventListener('DOMContentLoaded', function() {
    const searchForm = document.getElementById('searchForm');
    if (!searchForm) return;

    const marketGridContainer = document.getElementById('marketGridContainer');
    const activeFiltersContainer = document.getElementById('activeFiltersContainer');
    const resultsCountLabel = document.getElementById('resultsCountLabel');
    const sortBySelect = document.getElementById('sortBy');

    let debounceTimer;

    // Handle form submission via AJAX
    searchForm.addEventListener('submit', function(e) {
        e.preventDefault();
        performSearch();
    });

    // Auto-submit on select or checkbox changes
    const inputsToWatch = searchForm.querySelectorAll('select, input[type="checkbox"], input[type="radio"]');
    inputsToWatch.forEach(input => {
        input.addEventListener('change', () => {
            performSearch();
        });
    });

    // Handle clear filters
    const clearFiltersBtn = document.getElementById('clearFilters');
    if (clearFiltersBtn) {
        clearFiltersBtn.addEventListener('click', () => {
            searchForm.reset();
            const url = new URL(window.location);
            url.search = '';
            window.history.pushState({}, '', url);
            performSearch(true); // true means clear all
        });
    }

    // Bind sorting change
    if (sortBySelect) {
        sortBySelect.addEventListener('change', () => {
            performSearch();
        });
    }

    function performSearch(clearAll = false) {
        let url = new URL(searchForm.action || window.location.href);
        let params = new URLSearchParams(new FormData(searchForm));
        
        if (clearAll) {
            params = new URLSearchParams();
        }

        // Clean up empty params
        for (const [key, value] of Array.from(params.entries())) {
            if (!value) {
                params.delete(key);
            }
        }

        url.search = params.toString();

        // Update URL bar
        window.history.pushState({}, '', url);

        // Show loading state
        if (marketGridContainer) {
            marketGridContainer.style.opacity = '0.5';
            marketGridContainer.style.pointerEvents = 'none';
        }

        // Fetch new results
        fetch(url, {
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'Accept': 'application/json'
            }
        })
        .then(response => {
            if (!response.ok) throw new Error('Network response was not ok');
            return response.json();
        })
        .then(data => {
            if (marketGridContainer && data.grid_html) {
                marketGridContainer.innerHTML = data.grid_html;
            }
            if (activeFiltersContainer && data.active_filters_html) {
                activeFiltersContainer.innerHTML = data.active_filters_html;
            }
            if (resultsCountLabel && data.plots_count !== undefined) {
                resultsCountLabel.innerHTML = `${data.plots_count} ${data.plots_count === 1 ? 'plot' : 'plots'} found`;
            }
            if (data.seo_title) {
                document.title = data.seo_title;
            }
            
            // Rebind active filter remove buttons
            bindActiveFilterRemovals();
        })
        .catch(error => {
            console.error('Search failed:', error);
        })
        .finally(() => {
            if (marketGridContainer) {
                marketGridContainer.style.opacity = '1';
                marketGridContainer.style.pointerEvents = 'auto';
            }
        });
    }

    function bindActiveFilterRemovals() {
        const removeBtns = document.querySelectorAll('.remove-filter');
        removeBtns.forEach(btn => {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                // Find corresponding input and clear it
                const paramStr = this.getAttribute('data-params');
                if (paramStr) {
                    try {
                        // The backend passes Python list string like "['listing_type']". 
                        // It's tricky to parse. Alternatively, just fetch the href via AJAX.
                    } catch (e) {}
                }
                
                // Fallback: Just fetch the href URL directly
                const url = this.getAttribute('href');
                if (url) {
                    window.history.pushState({}, '', url);
                    
                    // Update form to match URL
                    const searchParams = new URLSearchParams(url.split('?')[1] || '');
                    Array.from(searchForm.elements).forEach(element => {
                        if (element.name) {
                            if (element.type === 'checkbox' || element.type === 'radio') {
                                element.checked = searchParams.getAll(element.name).includes(element.value);
                            } else {
                                element.value = searchParams.get(element.name) || '';
                            }
                        }
                    });
                    
                    performSearch();
                }
            });
        });
    }
    
    // Initial bind
    bindActiveFilterRemovals();
    
    // Handle back/forward navigation
    window.addEventListener('popstate', function() {
        window.location.reload();
    });
});
