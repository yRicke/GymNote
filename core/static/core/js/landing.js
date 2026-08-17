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

(() => {
    const { gsap, ScrollTrigger } = window;

    if (!gsap || !ScrollTrigger) return;

    gsap.registerPlugin(ScrollTrigger);

    const motion = gsap.matchMedia();

    motion.add("(prefers-reduced-motion: no-preference)", () => {
        gsap.utils.toArray("[data-section-transition]").forEach((transition) => {
            gsap.from(transition, {
                scaleX: 0,
                opacity: 0,
                duration: 1.15,
                ease: "power3.out",
                scrollTrigger: {
                    trigger: transition.parentElement,
                    start: "top 88%",
                    toggleActions: "play none none reverse",
                },
            });
        });

        const product = document.querySelector(".landing-product");
        if (product) {
            const productTimeline = gsap.timeline({
                defaults: { ease: "power3.out" },
                scrollTrigger: {
                    trigger: product,
                    start: "top 72%",
                    toggleActions: "play none none reverse",
                },
            });

            productTimeline
                .from(product.querySelector("[data-gsap-heading]").children, {
                    y: 34,
                    opacity: 0,
                    duration: .72,
                    stagger: .08,
                })
                .from(product.querySelectorAll("[data-gsap-card]"), {
                    y: 72,
                    opacity: 0,
                    scale: .975,
                    duration: .9,
                    stagger: .13,
                }, "-=.34")
                .from(product.querySelectorAll("[data-gsap-demo]"), {
                    y: 38,
                    opacity: 0,
                    duration: .72,
                    stagger: .1,
                }, "-=.58");
        }

        const contrast = document.querySelector(".landing-contrast");
        if (contrast) {
            const contrastTimeline = gsap.timeline({
                defaults: { ease: "power3.out" },
                scrollTrigger: {
                    trigger: contrast,
                    start: "top 70%",
                    toggleActions: "play none none reverse",
                },
            });

            contrastTimeline
                .from(contrast.querySelector("[data-contrast-copy]").children, {
                    x: -48,
                    opacity: 0,
                    duration: .75,
                    stagger: .09,
                })
                .from(contrast.querySelector(".comparison__note"), {
                    x: 68,
                    y: -24,
                    opacity: 0,
                    duration: .8,
                }, "-=.4")
                .from(contrast.querySelector(".comparison__structured"), {
                    x: 92,
                    y: 30,
                    opacity: 0,
                    duration: .9,
                }, "-=.58");
        }

        const flow = document.querySelector(".landing-steps");
        if (flow) {
            gsap.timeline({
                defaults: { ease: "power3.out" },
                scrollTrigger: {
                    trigger: flow,
                    start: "top 72%",
                    toggleActions: "play none none reverse",
                },
            }).from(flow.querySelector("[data-gsap-heading]").children, {
                y: 34,
                opacity: 0,
                duration: .7,
                stagger: .08,
            });

            flow.querySelectorAll("[data-flow-step]").forEach((step) => {
                gsap.timeline({
                    defaults: { ease: "power3.out" },
                    scrollTrigger: {
                        trigger: step,
                        start: "top 84%",
                        toggleActions: "play none none reverse",
                    },
                })
                    .from(step.querySelector("[data-flow-rule]"), {
                        scaleX: 0,
                        duration: .65,
                    })
                    .from([
                        step.querySelector(".flow-step__number"),
                        step.querySelector(".flow-step__copy"),
                    ], {
                        y: 28,
                        opacity: 0,
                        duration: .6,
                        stagger: .08,
                    }, "-=.48")
                    .from(step.querySelector(".flow-step__output"), {
                        x: 50,
                        opacity: 0,
                        duration: .66,
                    }, "-=.5");
            });
        }

        const cta = document.querySelector(".landing-cta");
        if (cta) {
            gsap.from(cta.querySelector(".landing-cta__content").children, {
                y: 34,
                opacity: 0,
                duration: .75,
                stagger: .08,
                ease: "power3.out",
                scrollTrigger: {
                    trigger: cta,
                    start: "top 76%",
                    toggleActions: "play none none reverse",
                },
            });
        }

        document.fonts?.ready.then(() => ScrollTrigger.refresh());
    });
})();
