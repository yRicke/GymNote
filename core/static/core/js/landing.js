(() => {
    const root = document.querySelector("[data-parallax-root]");
    const layers = root?.querySelectorAll("[data-parallax-speed]");
    const header = document.querySelector("[data-landing-header]");
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

    if (!root || !layers?.length) return;

    let frameRequested = false;

    const render = () => {
        const scrollTop = window.scrollY;
        const withinHero = scrollTop <= root.offsetHeight * 1.15;

        header?.classList.toggle("is-scrolled", scrollTop > 24);

        if (!reducedMotion.matches && withinHero) {
            const cappedScroll = Math.min(scrollTop, root.offsetHeight);
            layers.forEach((layer) => {
                const speed = Number(layer.dataset.parallaxSpeed || 0);
                layer.style.setProperty("--parallax-y", `${cappedScroll * speed}px`);
            });
        }

        frameRequested = false;
    };

    const requestRender = () => {
        if (!frameRequested) {
            window.requestAnimationFrame(render);
            frameRequested = true;
        }
    };

    reducedMotion.addEventListener?.("change", requestRender);
    window.addEventListener("scroll", requestRender, { passive: true });
    window.addEventListener("resize", requestRender, { passive: true });
    render();
})();
