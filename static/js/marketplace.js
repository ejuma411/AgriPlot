document.addEventListener("DOMContentLoaded", () => {
    const heroSlides = document.querySelectorAll(".hero-slider img");
    if (heroSlides.length > 0) {
        let heroIndex = 0;
        heroSlides.forEach((img, index) => img.classList.toggle("active", index === 0));
        setInterval(() => {
            heroSlides[heroIndex].classList.remove("active");
            heroIndex = (heroIndex + 1) % heroSlides.length;
            heroSlides[heroIndex].classList.add("active");
        }, 5000);
    }

    const filterToggle = document.getElementById("filterToggle");
    const advancedFilters = document.getElementById("advancedFilters");
    if (filterToggle && advancedFilters) {
        filterToggle.addEventListener("click", function () {
            const isVisible = advancedFilters.style.display === "block";
            advancedFilters.style.display = isVisible ? "none" : "block";
            const icon = this.querySelector("i");
            if (icon) {
                icon.className = isVisible ? "fas fa-sliders-h" : "fas fa-times";
            }
        });
    }

    const minPrice = document.querySelector('input[name="min_price"]');
    const maxPrice = document.querySelector('input[name="max_price"]');
    if (minPrice && maxPrice) {
        const validatePrice = () => {
            if (minPrice.value && maxPrice.value) {
                if (parseFloat(minPrice.value) > parseFloat(maxPrice.value)) {
                    maxPrice.setCustomValidity("Max price must be greater than min price");
                } else {
                    maxPrice.setCustomValidity("");
                }
            }
        };
        minPrice.addEventListener("change", validatePrice);
        maxPrice.addEventListener("change", validatePrice);
    }

    document.querySelectorAll('.plot-gallery').forEach((card) => {
        const images = card.querySelectorAll("img");
        if (images.length <= 1) {
            return;
        }

        let currentIndex = 0;
        let interval;
        images[0].classList.add("active");

        card.addEventListener("mouseenter", () => {
            interval = setInterval(() => {
                images[currentIndex].classList.remove("active");
                currentIndex = (currentIndex + 1) % images.length;
                images[currentIndex].classList.add("active");
            }, 1000);
        });

        card.addEventListener("mouseleave", () => {
            clearInterval(interval);
            images.forEach((img) => img.classList.remove("active"));
            images[0].classList.add("active");
            currentIndex = 0;
        });

        let touchStartX = 0;
        card.addEventListener("touchstart", (event) => {
            clearInterval(interval);
            touchStartX = event.touches[0].clientX;
        });

        card.addEventListener("touchend", (event) => {
            const touchEndX = event.changedTouches[0].clientX;
            const diff = touchStartX - touchEndX;

            if (Math.abs(diff) > 50) {
                images[currentIndex].classList.remove("active");
                if (diff > 0) {
                    currentIndex = (currentIndex + 1) % images.length;
                } else {
                    currentIndex = (currentIndex - 1 + images.length) % images.length;
                }
                images[currentIndex].classList.add("active");
            }
        });
    });

    document.querySelectorAll('a[href^="#"]:not([href="#"])').forEach((anchor) => {
        anchor.addEventListener("click", function (event) {
            const targetId = this.getAttribute("href");
            if (!targetId || targetId === "#") {
                return;
            }
            const target = document.querySelector(targetId);
            if (target) {
                event.preventDefault();
                target.scrollIntoView({ behavior: "smooth", block: "start" });
            }
        });
    });

    document.querySelectorAll(".fav-btn").forEach((button) => {
        button.addEventListener("click", function () {
            const icon = this.querySelector("i");
            if (icon) {
                icon.classList.toggle("far");
                icon.classList.toggle("fas");
                this.classList.toggle("active");
            }
        });
    });
});

(function () {
    const form = document.getElementById("searchForm");
    if (!form) {
        return;
    }

    const clearFiltersButton = document.getElementById("clearFilters");
    const countySelect = form.querySelector('select[name="county"]');
    const subcountySelect = form.querySelector('select[name="subcounty"]');
    const subcountyUrl = form.dataset.subcountyUrl;

    async function refreshSubcounties(selectedValue = "") {
        if (!countySelect || !subcountySelect || !subcountyUrl) {
            return;
        }
        const county = countySelect.value;
        subcountySelect.innerHTML = '<option value="">Any sub-county</option>';
        if (!county) {
            return;
        }

        try {
            const response = await fetch(`${subcountyUrl}?county=${encodeURIComponent(county)}`, {
                headers: { "X-Requested-With": "XMLHttpRequest" },
            });
            const data = await response.json();
            for (const subcounty of data.subcounties || []) {
                const option = document.createElement("option");
                option.value = subcounty;
                option.textContent = subcounty;
                if (subcounty === selectedValue) {
                    option.selected = true;
                }
                subcountySelect.appendChild(option);
            }
        } catch (error) {
            console.error("Error fetching subcounties:", error);
        }
    }

    if (countySelect) {
        countySelect.addEventListener("change", () => refreshSubcounties());
    }

    if (clearFiltersButton) {
        clearFiltersButton.addEventListener("click", async () => {
            form.reset();
            await refreshSubcounties();
        });
    }
})();

(function () {
    const scrollToResultsFlag = sessionStorage.getItem("scrollToResults");
    if (scrollToResultsFlag) {
        const resultsHeader = document.getElementById("resultsHeader");
        if (resultsHeader) {
            setTimeout(() => resultsHeader.scrollIntoView({ behavior: "smooth", block: "start" }), 100);
        }
        sessionStorage.removeItem("scrollToResults");
    }

    const form = document.getElementById("searchForm");
    if (form) {
        form.addEventListener("submit", () => sessionStorage.setItem("scrollToResults", "true"));
    }
})();
