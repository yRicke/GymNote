(() => {
    const debounce = (callback, wait = 300) => {
        let timeout;
        const debounced = (...args) => {
            window.clearTimeout(timeout);
            timeout = window.setTimeout(() => callback(...args), wait);
        };
        debounced.cancel = () => window.clearTimeout(timeout);
        return debounced;
    };

    const searchRegion = document.querySelector("[data-exercise-search-region]");
    if (searchRegion) {
        const searchForm = searchRegion.querySelector("[data-live-search]");
        const searchInput = searchForm.querySelector('input[type="search"]');
        const clearSearch = searchForm.querySelector("[data-search-clear]");
        const resultsContainer = searchRegion.querySelector("[data-exercise-results]");
        const countBadge = searchRegion.querySelector("[data-search-count]");
        const status = searchRegion.querySelector("[data-search-status]");
        const selectionForm = searchRegion.querySelector("[data-exercise-selection-form]");
        const preservedSelections = selectionForm.querySelector("[data-preserved-selections]");
        const selectionSubmit = selectionForm.querySelector("[data-exercise-submit]");
        const selectedExerciseIds = new Set(
            [...resultsContainer.querySelectorAll('input[name="exercises"]:checked')].map(
                (input) => input.value,
            ),
        );
        let activeRequest = null;
        let requestSequence = 0;

        const updateSelectionButton = () => {
            selectionSubmit.disabled = selectedExerciseIds.size === 0;
            selectionSubmit.setAttribute(
                "aria-label",
                selectedExerciseIds.size
                    ? `Adicionar ${selectedExerciseIds.size} exercício${selectedExerciseIds.size === 1 ? "" : "s"} selecionado${selectedExerciseIds.size === 1 ? "" : "s"}`
                    : "Selecione ao menos um exercício",
            );
        };
        const restoreSelections = () => {
            resultsContainer
                .querySelectorAll('input[name="exercises"]')
                .forEach((input) => {
                    input.checked = selectedExerciseIds.has(input.value);
                });
            updateSelectionButton();
        };
        const updateAddress = (query) => {
            const address = new URL(searchForm.action, window.location.origin);
            if (query) address.searchParams.set("q", query);
            window.history.replaceState({}, "", `${address.pathname}${address.search}`);
        };
        const performSearch = async () => {
            const query = searchInput.value.trim();
            const requestId = ++requestSequence;
            activeRequest?.abort();
            activeRequest = new AbortController();
            const requestUrl = new URL(searchForm.action, window.location.origin);
            if (query) requestUrl.searchParams.set("q", query);

            searchRegion.classList.add("is-loading");
            searchRegion.setAttribute("aria-busy", "true");
            status.textContent = "Buscando exercícios…";
            try {
                const response = await fetch(requestUrl, {
                    credentials: "same-origin",
                    headers: {
                        Accept: "application/json",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    signal: activeRequest.signal,
                });
                if (!response.ok) throw new Error("Não foi possível atualizar a busca.");
                const data = await response.json();
                if (requestId !== requestSequence) return;

                resultsContainer.innerHTML = data.html;
                restoreSelections();
                countBadge.textContent = `${data.count} ${data.count === 1 ? "disponível" : "disponíveis"}`;
                clearSearch.hidden = !data.query;
                updateAddress(data.query);
                status.textContent = `${data.count} exercício${data.count === 1 ? "" : "s"} encontrado${data.count === 1 ? "" : "s"}.`;
            } catch (error) {
                if (error.name !== "AbortError") status.textContent = error.message;
            } finally {
                if (requestId === requestSequence) {
                    searchRegion.classList.remove("is-loading");
                    searchRegion.removeAttribute("aria-busy");
                }
            }
        };
        const scheduleSearch = debounce(performSearch, 250);

        searchInput.addEventListener("input", scheduleSearch);
        searchForm.addEventListener("submit", (event) => {
            event.preventDefault();
            scheduleSearch.cancel();
            performSearch();
        });
        clearSearch.addEventListener("click", (event) => {
            event.preventDefault();
            scheduleSearch.cancel();
            searchInput.value = "";
            searchInput.focus();
            performSearch();
        });
        selectionForm.addEventListener("change", (event) => {
            if (!event.target.matches('input[name="exercises"]')) return;
            if (event.target.checked) selectedExerciseIds.add(event.target.value);
            else selectedExerciseIds.delete(event.target.value);
            updateSelectionButton();
        });
        selectionForm.addEventListener("submit", (event) => {
            if (!selectedExerciseIds.size) {
                event.preventDefault();
                status.textContent = "Selecione ao menos um exercício.";
                return;
            }
            preservedSelections.replaceChildren();
            const visibleIds = new Set(
                [...resultsContainer.querySelectorAll('input[name="exercises"]')].map(
                    (input) => input.value,
                ),
            );
            selectedExerciseIds.forEach((exerciseId) => {
                if (visibleIds.has(exerciseId)) return;
                const hiddenInput = document.createElement("input");
                hiddenInput.type = "hidden";
                hiddenInput.name = "exercises";
                hiddenInput.value = exerciseId;
                preservedSelections.append(hiddenInput);
            });
        });
        updateSelectionButton();
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
