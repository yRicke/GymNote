(() => {
    const debounce = (callback, wait = 300) => {
        let timeout;
        return (...args) => {
            window.clearTimeout(timeout);
            timeout = window.setTimeout(() => callback(...args), wait);
        };
    };

    const autoSearchForm = document.querySelector("[data-auto-search]");
    if (autoSearchForm) {
        const searchInput = autoSearchForm.querySelector('input[type="search"]');
        const submitSearch = debounce(() => {
            autoSearchForm.setAttribute("aria-busy", "true");
            autoSearchForm.requestSubmit();
        });
        searchInput?.addEventListener("input", submitSearch);
    }

    const autoFilterForm = document.querySelector("[data-auto-filter]");
    if (autoFilterForm) {
        autoFilterForm.addEventListener("change", (event) => {
            if (!event.target.matches('input[type="checkbox"]')) return;
            autoFilterForm.setAttribute("aria-busy", "true");
            autoFilterForm.requestSubmit();
        });
    }

    document.querySelectorAll("[data-reorder-list]").forEach((list) => {
        const status = list.parentElement.querySelector("[data-reorder-status]");
        const csrfToken = list.querySelector("[data-csrf-token]")?.value;
        let draggedItem = null;
        let dragEnabled = false;
        let touchChanged = false;

        const items = () => [...list.querySelectorAll("[data-reorder-id]")];
        const announce = (message) => {
            if (status) status.textContent = message;
        };
        const moveItem = (item, direction) => {
            const sibling = direction < 0 ? item.previousElementSibling : item.nextElementSibling;
            if (!sibling || !sibling.matches("[data-reorder-id]")) return false;
            if (direction < 0) list.insertBefore(item, sibling);
            else list.insertBefore(sibling, item);
            return true;
        };
        const persistOrder = async () => {
            const order = items().map((item) => Number(item.dataset.reorderId));
            list.classList.add("is-saving");
            announce("Salvando nova ordem…");
            try {
                const response = await fetch(list.dataset.reorderUrl, {
                    method: "POST",
                    credentials: "same-origin",
                    headers: {
                        "Content-Type": "application/json",
                        "X-CSRFToken": csrfToken,
                    },
                    body: JSON.stringify({ order }),
                });
                if (!response.ok) throw new Error("Não foi possível salvar a ordem.");
                announce("Ordem dos exercícios atualizada.");
            } catch (error) {
                announce(error.message);
                window.setTimeout(() => window.location.reload(), 900);
            } finally {
                list.classList.remove("is-saving");
            }
        };

        items().forEach((item) => {
            const handle = item.querySelector(".drag-handle");
            handle?.addEventListener("pointerdown", (event) => {
                dragEnabled = true;
                if (event.pointerType === "mouse") return;
                event.preventDefault();
                draggedItem = item;
                touchChanged = false;
                item.classList.add("is-dragging");
                handle.setPointerCapture(event.pointerId);
            });
            item.addEventListener("pointerdown", (event) => {
                if (!event.target.closest(".drag-handle")) dragEnabled = false;
            });
            handle?.addEventListener("pointermove", (event) => {
                if (!draggedItem || event.pointerType === "mouse") return;
                event.preventDefault();
                const target = document
                    .elementFromPoint(event.clientX, event.clientY)
                    ?.closest("[data-reorder-id]");
                if (!target || target === draggedItem || target.parentElement !== list) return;
                const targetBox = target.getBoundingClientRect();
                const after = event.clientY > targetBox.top + targetBox.height / 2;
                list.insertBefore(draggedItem, after ? target.nextSibling : target);
                touchChanged = true;
            });
            const finishPointerReorder = (event) => {
                if (!draggedItem || event.pointerType === "mouse") return;
                draggedItem.classList.remove("is-dragging");
                draggedItem = null;
                dragEnabled = false;
                if (touchChanged) persistOrder();
            };
            handle?.addEventListener("pointerup", finishPointerReorder);
            handle?.addEventListener("pointercancel", finishPointerReorder);
            handle?.addEventListener("keydown", (event) => {
                if (!['ArrowUp', 'ArrowDown'].includes(event.key)) return;
                event.preventDefault();
                if (moveItem(item, event.key === "ArrowUp" ? -1 : 1)) {
                    handle.focus();
                    persistOrder();
                }
            });
            item.addEventListener("dragstart", (event) => {
                if (!dragEnabled) {
                    event.preventDefault();
                    return;
                }
                draggedItem = item;
                item.classList.add("is-dragging");
                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData("text/plain", item.dataset.reorderId);
            });
            item.addEventListener("dragend", () => {
                if (!draggedItem) return;
                item.classList.remove("is-dragging");
                draggedItem = null;
                dragEnabled = false;
                persistOrder();
            });
        });
        list.addEventListener("dragover", (event) => {
            if (!draggedItem) return;
            event.preventDefault();
            const target = event.target.closest("[data-reorder-id]");
            if (!target || target === draggedItem) return;
            const targetBox = target.getBoundingClientRect();
            const after = event.clientY > targetBox.top + targetBox.height / 2;
            list.insertBefore(draggedItem, after ? target.nextSibling : target);
        });
    });
})();
