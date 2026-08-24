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

    const normalizeSearch = (value) =>
        value
            .normalize("NFD")
            .replace(/[\u0300-\u036f]/g, "")
            .toLocaleLowerCase("pt-BR")
            .trim();

    const catalogControllers = new Map();

    document.querySelectorAll("[data-exercise-search-region]").forEach((searchRegion) => {
        const dialog = searchRegion.closest("dialog");
        const searchInput = searchRegion.querySelector("[data-catalog-search]");
        const clearSearch = searchRegion.querySelector("[data-search-clear]");
        const resultsContainer = searchRegion.querySelector("[data-exercise-results]");
        const countBadge = searchRegion.querySelector("[data-search-count]");
        const status = searchRegion.querySelector("[data-search-status]");
        const selectionForm = searchRegion.closest("form");
        const preservedSelections = searchRegion.querySelector("[data-preserved-selections]");
        const selectionSubmit = selectionForm?.querySelector("[data-exercise-submit]");
        const searchUrl = searchRegion.dataset.catalogSearchUrl;
        const selectedExerciseIds = new Set();
        const selectionOrder = [];
        let committedSelectionOrder = [];
        let activeRequest = null;
        let requestSequence = 0;
        let pendingFocusId = null;

        const optionInputs = () => [
            ...resultsContainer.querySelectorAll('input[name="exercises"]'),
        ];
        const rememberSelection = (exerciseId) => {
            selectedExerciseIds.add(exerciseId);
            if (!selectionOrder.includes(exerciseId)) selectionOrder.push(exerciseId);
        };
        const forgetSelection = (exerciseId) => {
            selectedExerciseIds.delete(exerciseId);
            const index = selectionOrder.indexOf(exerciseId);
            if (index >= 0) selectionOrder.splice(index, 1);
        };
        const readDefaultSelections = () => {
            selectedExerciseIds.clear();
            selectionOrder.splice(0);
            optionInputs().forEach((input) => {
                input.checked = input.defaultChecked;
                if (input.defaultChecked) rememberSelection(input.value);
            });
        };
        const updateSelectionButton = () => {
            if (!selectionSubmit) return;
            if (searchRegion.dataset.catalogMode === "workout") {
                selectionSubmit.disabled = selectedExerciseIds.size === 0;
            }
            selectionSubmit.setAttribute(
                "aria-label",
                selectedExerciseIds.size
                    ? `${selectedExerciseIds.size} exercício${selectedExerciseIds.size === 1 ? "" : "s"} selecionado${selectedExerciseIds.size === 1 ? "" : "s"}`
                    : "Selecione ao menos um exercício",
            );
        };
        const restoreSelections = () => {
            optionInputs().forEach((input) => {
                input.checked = selectedExerciseIds.has(input.value);
            });
            updateSelectionButton();
        };
        const rowForInput = (input) => {
            const label = input.closest("label");
            return label?.closest("li") || label?.parentElement;
        };
        const filterLocalOptions = () => {
            const query = normalizeSearch(searchInput.value);
            let visibleCount = 0;
            optionInputs().forEach((input) => {
                const row = rowForInput(input);
                const exerciseName = normalizeSearch(
                    input.closest("label")?.querySelector(".exercise-choice__name")?.textContent || "",
                );
                const visible = !query || exerciseName.includes(query);
                if (row) row.hidden = !visible;
                if (visible) visibleCount += 1;
            });
            countBadge.textContent = `${visibleCount} ${visibleCount === 1 ? "disponível" : "disponíveis"}`;
            clearSearch.hidden = !query;
            status.textContent = `${visibleCount} exercício${visibleCount === 1 ? "" : "s"} encontrado${visibleCount === 1 ? "" : "s"}.`;
        };
        const performSearch = async () => {
            if (!searchUrl) {
                filterLocalOptions();
                return;
            }
            const query = searchInput.value.trim();
            const requestId = ++requestSequence;
            activeRequest?.abort();
            activeRequest = new AbortController();
            const requestUrl = new URL(searchUrl, window.location.origin);
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
        const addExerciseOption = async (exercise) => {
            searchInput.value = "";
            clearSearch.hidden = true;
            let input = optionInputs().find((option) => option.value === String(exercise.id));
            rememberSelection(String(exercise.id));
            if (searchUrl) {
                await performSearch();
                input = optionInputs().find((option) => option.value === String(exercise.id));
            } else if (!input) {
                const optionsRoot = resultsContainer.querySelector(".choice-list > div")
                    || resultsContainer.querySelector(".choice-list ul")
                    || resultsContainer.querySelector(".choice-list");
                if (optionsRoot) {
                    const row = document.createElement(optionsRoot.matches("ul") ? "li" : "div");
                    const label = document.createElement("label");
                    input = document.createElement("input");
                    input.type = "checkbox";
                    input.name = "exercises";
                    input.value = String(exercise.id);
                    input.id = `id_exercises_created_${exercise.id}`;
                    label.htmlFor = input.id;
                    const name = document.createElement("span");
                    name.className = "exercise-choice__name";
                    name.textContent = exercise.name;
                    const metadata = document.createElement("span");
                    metadata.className = "exercise-choice__meta";
                    if (exercise.is_custom) {
                        const personal = document.createElement("span");
                        personal.className = "exercise-choice__personal material-symbols-outlined";
                        personal.textContent = "person";
                        personal.setAttribute("role", "img");
                        personal.setAttribute("aria-label", "Exercício pessoal");
                        personal.title = "Exercício pessoal";
                        metadata.append(personal);
                    }
                    const group = document.createElement("span");
                    group.className = "exercise-choice__group";
                    group.textContent = exercise.group.name;
                    metadata.append(group);
                    label.append(input, name, metadata);
                    row.append(label);
                    optionsRoot.prepend(row);
                }
            }
            if (!input) return;
            input.checked = true;
            input.defaultChecked = searchRegion.dataset.catalogMode === "workout" ? false : input.defaultChecked;
            if (!searchUrl) filterLocalOptions();
            restoreSelections();
            pendingFocusId = String(exercise.id);
        };
        const focusPendingExercise = () => {
            if (!pendingFocusId) return false;
            const input = optionInputs().find((option) => option.value === pendingFocusId);
            pendingFocusId = null;
            if (!input) return false;
            rowForInput(input)?.scrollIntoView({ block: "nearest" });
            input.focus({ preventScroll: true });
            return true;
        };
        const resetDraft = () => {
            scheduleSearch.cancel();
            searchInput.value = "";
            clearSearch.hidden = true;
            readDefaultSelections();
            const defaultOrder = [...selectionOrder];
            selectionOrder.splice(0);
            committedSelectionOrder.forEach((exerciseId) => {
                if (selectedExerciseIds.has(exerciseId)) selectionOrder.push(exerciseId);
            });
            defaultOrder.forEach((exerciseId) => {
                if (!selectionOrder.includes(exerciseId)) selectionOrder.push(exerciseId);
            });
            if (searchUrl) performSearch();
            else filterLocalOptions();
            updateSelectionButton();
        };
        const commitDraft = () => {
            optionInputs().forEach((input) => {
                input.defaultChecked = selectedExerciseIds.has(input.value);
                input.checked = input.defaultChecked;
            });
            committedSelectionOrder = [...selectionOrder];
        };

        searchInput.addEventListener("input", scheduleSearch);
        searchInput.addEventListener("keydown", (event) => {
            if (event.key === "Enter") event.preventDefault();
        });
        clearSearch.addEventListener("click", () => {
            scheduleSearch.cancel();
            searchInput.value = "";
            searchInput.focus();
            performSearch();
        });
        selectionForm?.addEventListener("change", (event) => {
            if (!event.target.matches('input[name="exercises"]')) return;
            if (event.target.checked) rememberSelection(event.target.value);
            else forgetSelection(event.target.value);
            updateSelectionButton();
        });
        if (searchRegion.dataset.catalogMode === "workout") {
            selectionForm?.addEventListener("submit", (event) => {
                if (!selectedExerciseIds.size) {
                    event.preventDefault();
                    status.textContent = "Selecione ao menos um exercício.";
                    return;
                }
                preservedSelections.replaceChildren();
                const visibleIds = new Set(optionInputs().map((input) => input.value));
                selectionOrder.forEach((exerciseId) => {
                    if (visibleIds.has(exerciseId)) return;
                    const hiddenInput = document.createElement("input");
                    hiddenInput.type = "hidden";
                    hiddenInput.name = "exercises";
                    hiddenInput.value = exerciseId;
                    preservedSelections.append(hiddenInput);
                });
            });
        }

        readDefaultSelections();
        committedSelectionOrder = [...selectionOrder];
        updateSelectionButton();
        if (!searchUrl) filterLocalOptions();
        catalogControllers.set(dialog, {
            addExerciseOption,
            resetDraft,
            selectedExerciseIds,
            selectionOrder,
            restoreSelections,
            focusPendingExercise,
            optionInputs,
            commitDraft,
        });
    });

    const presetBuilder = document.querySelector("[data-preset-builder]");
    const presetCatalogDialog = presetBuilder?.querySelector("#exercise-catalog-dialog");
    const presetCatalog = catalogControllers.get(presetCatalogDialog);
    if (presetBuilder && presetCatalogDialog && presetCatalog) {
        const orderInput = presetBuilder.querySelector('input[name="exercise_order"]');
        const selectedList = presetBuilder.querySelector("[data-preset-selected-list]");
        const selectedCount = presetBuilder.querySelector("[data-preset-selected-count]");
        const emptyState = presetBuilder.querySelector("[data-preset-selection-empty]");
        const selectionStatus = presetBuilder.querySelector("[data-preset-selection-status]");
        const confirmButton = presetCatalogDialog.querySelector("[data-catalog-confirm]");
        const initialMetadata = new Map(
            [...selectedList.querySelectorAll("[data-selected-exercise-id]")].map((item) => [
                item.dataset.selectedExerciseId,
                {
                    name: item.dataset.selectedExerciseName || "",
                    group: item.dataset.selectedExerciseGroup || "",
                    isCustom: item.dataset.selectedExerciseCustom === "true",
                },
            ]),
        );
        const metadataForInput = (input) => {
            const label = input.closest("label");
            return {
                name: label?.querySelector(".exercise-choice__name")?.textContent.trim() || "",
                group: label?.querySelector(".exercise-choice__group")?.textContent.trim() || "",
                isCustom: Boolean(label?.querySelector(".exercise-choice__personal")),
            };
        };
        const orderedSelectedIds = () => presetCatalog.selectionOrder.filter(
            (exerciseId) => presetCatalog.selectedExerciseIds.has(exerciseId),
        );
        const createSelectionItem = (exerciseId, metadata) => {
            const item = document.createElement("article");
            item.className = "list-card list-card--actions preset-builder__selected-item reorderable-item";
            item.dataset.selectedExerciseId = exerciseId;
            item.dataset.selectedExerciseName = metadata.name;
            item.dataset.selectedExerciseGroup = metadata.group;
            item.dataset.selectedExerciseCustom = String(metadata.isCustom);
            item.draggable = false;

            const handle = document.createElement("button");
            handle.className = "drag-handle icon-button";
            handle.type = "button";
            handle.title = "Arraste para reordenar";
            handle.setAttribute("aria-label", `Arrastar ${metadata.name} para mudar a ordem`);
            const handleIcon = document.createElement("span");
            handleIcon.className = "material-symbols-outlined";
            handleIcon.setAttribute("aria-hidden", "true");
            handleIcon.draggable = false;
            handleIcon.textContent = "drag_indicator";
            handle.append(handleIcon);

            const main = document.createElement("span");
            main.className = "preset-builder__selected-main";
            const name = document.createElement("strong");
            name.className = "preset-builder__selected-name";
            name.textContent = metadata.name;
            const meta = document.createElement("span");
            meta.className = "exercise-choice__meta";
            if (metadata.isCustom) {
                const personal = document.createElement("span");
                personal.className = "exercise-choice__personal material-symbols-outlined";
                personal.setAttribute("role", "img");
                personal.setAttribute("aria-label", "Exercício pessoal");
                personal.title = "Exercício pessoal";
                personal.textContent = "person";
                meta.append(personal);
            }
            const group = document.createElement("span");
            group.className = "exercise-choice__group";
            group.textContent = metadata.group;
            meta.append(group);
            main.append(name, meta);

            const remove = document.createElement("button");
            remove.className = "icon-button icon-button--danger preset-builder__remove";
            remove.type = "button";
            remove.dataset.removeSelectedExercise = "";
            remove.setAttribute("aria-label", `Remover ${metadata.name} da predefinição`);
            remove.title = "Remover da predefinição";
            const removeIcon = document.createElement("span");
            removeIcon.className = "material-symbols-outlined";
            removeIcon.setAttribute("aria-hidden", "true");
            removeIcon.textContent = "close";
            remove.append(removeIcon);

            item.append(handle, main, remove);
            return item;
        };
        const renderSelection = () => {
            const inputsById = new Map(
                presetCatalog.optionInputs().map((input) => [input.value, input]),
            );
            const selectedIds = orderedSelectedIds();
            selectedList.replaceChildren();
            selectedIds.forEach((exerciseId) => {
                const input = inputsById.get(exerciseId);
                if (!input) return;
                const metadata = initialMetadata.get(exerciseId) || metadataForInput(input);
                selectedList.append(createSelectionItem(exerciseId, metadata));
            });
            selectedList.hidden = selectedIds.length === 0;
            emptyState.hidden = selectedIds.length !== 0;
            selectedCount.textContent = `${selectedIds.length} selecionado${selectedIds.length === 1 ? "" : "s"}`;
            orderInput.value = selectedIds.join(",");
        };

        const submittedOrder = orderInput.value
            .split(",")
            .filter((exerciseId) => presetCatalog.selectedExerciseIds.has(exerciseId));
        presetCatalog.selectionOrder.forEach((exerciseId) => {
            if (
                presetCatalog.selectedExerciseIds.has(exerciseId)
                && !submittedOrder.includes(exerciseId)
            ) submittedOrder.push(exerciseId);
        });
        presetCatalog.selectionOrder.splice(0, presetCatalog.selectionOrder.length, ...submittedOrder);
        presetCatalog.commitDraft();

        window.GymNoteSortable.create(selectedList, {
            itemSelector: "[data-selected-exercise-id]",
            onOrderChange: (orderedItems, movedItem) => {
                const reorderedIds = orderedItems.map((item) => item.dataset.selectedExerciseId);
                presetCatalog.selectionOrder.splice(
                    0,
                    presetCatalog.selectionOrder.length,
                    ...reorderedIds,
                );
                presetCatalog.commitDraft();
                orderInput.value = reorderedIds.join(",");
                const position = reorderedIds.indexOf(movedItem.dataset.selectedExerciseId) + 1;
                selectionStatus.textContent = `${movedItem.dataset.selectedExerciseName} movido para a posição ${position}.`;
            },
        });
        selectedList.addEventListener("click", (event) => {
            const removeButton = event.target.closest("[data-remove-selected-exercise]");
            if (!removeButton) return;
            const item = removeButton.closest("[data-selected-exercise-id]");
            const exerciseId = item?.dataset.selectedExerciseId;
            if (!exerciseId) return;
            const exerciseName = item.dataset.selectedExerciseName;
            presetCatalog.selectedExerciseIds.delete(exerciseId);
            const orderIndex = presetCatalog.selectionOrder.indexOf(exerciseId);
            if (orderIndex >= 0) presetCatalog.selectionOrder.splice(orderIndex, 1);
            const input = presetCatalog.optionInputs().find((option) => option.value === exerciseId);
            if (input) {
                input.checked = false;
                input.defaultChecked = false;
            }
            presetCatalog.commitDraft();
            renderSelection();
            selectionStatus.textContent = `${exerciseName} removido da predefinição.`;
        });

        confirmButton.addEventListener("click", () => {
            presetCatalog.commitDraft();
            renderSelection();
            presetCatalogDialog.close("confirmed");
        });
        presetBuilder.addEventListener("submit", () => {
            orderInput.value = orderedSelectedIds().join(",");
        });
    }

    const dialogOpeners = new Map();
    const dialogParents = new Map();
    const nestedDialogOpeners = new Map();
    const resetDialog = (dialog) => {
        const form = dialog.querySelector(
            "[data-dialog-form], [data-reset-dialog-form]",
        );
        if (!form) return;
        form.reset();
        form.removeAttribute("aria-busy");
        form.dataset.submitting = "false";
        form.querySelectorAll("button, input").forEach((control) => {
            control.disabled = false;
        });
        const submit = form.querySelector("[data-dialog-submit]");
        if (submit) {
            submit.textContent = submit.dataset.idleText;
            if (form.matches("[data-preset-selection-form]")) submit.disabled = true;
        }
        const errors = form.querySelector("[data-dialog-errors]");
        if (errors) {
            errors.hidden = true;
            errors.replaceChildren();
        }
    };
    const showDialogErrors = (form, data) => {
        const errors = form.querySelector("[data-dialog-errors]");
        if (!errors) return;
        const messages = data.errors
            ? Object.values(data.errors).flat()
            : [data.message || "Não foi possível concluir. Tente novamente."];
        errors.replaceChildren();
        messages.forEach((message) => {
            const paragraph = document.createElement("p");
            paragraph.textContent = message;
            errors.append(paragraph);
        });
        errors.hidden = false;
        errors.focus({ preventScroll: true });
    };
    const exerciseSetValuesElement = document.getElementById("exercise-set-form-values");
    const exerciseSetValues = exerciseSetValuesElement
        ? JSON.parse(exerciseSetValuesElement.textContent)
        : {};
    const emptyExerciseSetValues = {
        weight_kg: "",
        reps: "",
        partial_reps: "",
        duration_minutes: "",
        distance_km: "",
        perceived_exertion: "",
        is_working_set: false,
    };
    const configureSetDialog = (dialog, opener) => {
        const form = dialog.querySelector("[data-set-form]");
        if (!form || !opener.dataset.setFormMode) return;
        const isEditing = opener.dataset.setFormMode === "edit";
        const values = isEditing
            ? exerciseSetValues[opener.dataset.setId] || emptyExerciseSetValues
            : emptyExerciseSetValues;

        form.action = opener.dataset.setAction;
        dialog.querySelector("[data-set-dialog-title]").textContent =
            opener.dataset.setTitle;
        dialog.querySelector("[data-set-dialog-eyebrow]").textContent =
            opener.dataset.setEyebrow;
        dialog.querySelector("[data-set-dialog-icon]").textContent =
            isEditing ? "edit" : "add";
        Object.entries(values).forEach(([fieldName, value]) => {
            const field = form.elements.namedItem(fieldName);
            if (!field) return;
            if (field.type === "checkbox") field.checked = Boolean(value);
            else field.value = value;
        });
        form.querySelectorAll(".field-error, .errorlist").forEach((error) => {
            error.remove();
        });

        const submit = form.querySelector("[data-dialog-submit]");
        submit.dataset.idleText = isEditing
            ? "Salvar alterações"
            : opener.dataset.setTitle;
        submit.dataset.loadingText = "Salvando…";
        submit.textContent = submit.dataset.idleText;
    };

    document.querySelectorAll("[data-dialog-open]").forEach((opener) => {
        opener.addEventListener("click", (event) => {
            const dialog = document.getElementById(opener.dataset.dialogOpen);
            if (!dialog || typeof dialog.showModal !== "function") return;
            event.preventDefault();
            dialogOpeners.set(dialog, opener);
            const deleteForm = dialog.querySelector("[data-delete-dialog-form]");
            if (deleteForm && opener.dataset.deleteUrl) {
                deleteForm.action = opener.dataset.deleteUrl;
                dialog.querySelector("[data-delete-dialog-title]").textContent =
                    opener.dataset.deleteTitle;
                dialog.querySelector("[data-delete-dialog-copy]").textContent =
                    opener.dataset.deleteCopy;
            }
            resetDialog(dialog);
            configureSetDialog(dialog, opener);
            catalogControllers.get(dialog)?.resetDraft();
            dialog.returnValue = "";
            dialog.showModal();
            window.requestAnimationFrame(() => {
                const firstField = dialog.querySelector(
                    'input:not([type="hidden"]):not(:disabled)',
                );
                firstField?.focus({ preventScroll: true });
            });
        });
    });

    document.querySelectorAll("[data-nested-dialog-open]").forEach((opener) => {
        opener.addEventListener("click", (event) => {
            const parentDialog = opener.closest("dialog");
            const childDialog = document.getElementById(opener.dataset.nestedDialogOpen);
            if (!parentDialog || !childDialog || typeof childDialog.showModal !== "function") return;
            event.preventDefault();
            dialogParents.set(childDialog, parentDialog);
            nestedDialogOpeners.set(childDialog, opener);
            parentDialog.close("nested");
            resetDialog(childDialog);
            childDialog.returnValue = "";
            childDialog.showModal();
            window.requestAnimationFrame(() => {
                childDialog.querySelector('input:not([type="hidden"]):not(:disabled)')?.focus({ preventScroll: true });
            });
        });
    });

    document.querySelectorAll(".preset-dialog").forEach((dialog) => {
        dialog.querySelectorAll("[data-dialog-close]").forEach((button) => {
            button.addEventListener("click", () => dialog.close());
        });
        dialog.addEventListener("click", (event) => {
            if (event.target === dialog) dialog.close();
        });
        dialog.addEventListener("close", () => {
            if (dialog.returnValue === "nested") return;
            if (dialog.returnValue !== "confirmed") {
                catalogControllers.get(dialog)?.resetDraft();
            }
            resetDialog(dialog);
            const parentDialog = dialogParents.get(dialog);
            if (parentDialog) {
                dialogParents.delete(dialog);
                parentDialog.returnValue = "";
                parentDialog.showModal();
                window.requestAnimationFrame(() => {
                    if (!catalogControllers.get(parentDialog)?.focusPendingExercise()) {
                        nestedDialogOpeners.get(dialog)?.focus({ preventScroll: true });
                    }
                });
                nestedDialogOpeners.delete(dialog);
                return;
            }
            dialogOpeners.get(dialog)?.focus({ preventScroll: true });
            dialogOpeners.delete(dialog);
        });
    });

    document.querySelectorAll("[data-dialog-auto-open]").forEach((dialog) => {
        if (typeof dialog.showModal !== "function") return;
        if (dialog.open) dialog.close();
        dialog.showModal();
        window.requestAnimationFrame(() => {
            const firstErrorField = dialog
                .querySelector(".field-error")
                ?.closest(".field")
                ?.querySelector("input");
            const firstField = firstErrorField || dialog.querySelector(
                'input:not([type="hidden"]):not(:disabled)',
            );
            firstField?.focus({ preventScroll: true });
        });
    });

    document.querySelectorAll("[data-preset-selection-form]").forEach((form) => {
        const submit = form.querySelector("[data-dialog-submit]");
        form.addEventListener("change", (event) => {
            if (!event.target.matches('input[name="preset_id"]')) return;
            submit.disabled = !form.querySelector('input[name="preset_id"]:checked');
        });
    });

    document.querySelectorAll("[data-dialog-form]").forEach((form) => {
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            if (form.dataset.submitting === "true") return;

            const submit = form.querySelector("[data-dialog-submit]");
            const errors = form.querySelector("[data-dialog-errors]");
            const formData = new FormData(form);
            form.dataset.submitting = "true";
            form.setAttribute("aria-busy", "true");
            if (errors) errors.hidden = true;
            form.querySelectorAll("button, input").forEach((control) => {
                control.disabled = true;
            });
            submit.textContent = submit.dataset.loadingText;

            try {
                const response = await fetch(form.action, {
                    method: "POST",
                    credentials: "same-origin",
                    headers: {
                        Accept: "application/json",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    body: formData,
                });
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    showDialogErrors(form, data);
                    return;
                }
                const dialog = form.closest("dialog");
                const parentDialog = dialogParents.get(dialog);
                if (
                    parentDialog
                    && form.matches("[data-exercise-create-form]")
                    && data.exercise
                ) {
                    await catalogControllers.get(parentDialog)?.addExerciseOption(data.exercise);
                    dialog.close("created");
                    return;
                }
                window.location.reload();
            } catch (error) {
                showDialogErrors(form, {
                    message: "Não foi possível conectar. Verifique sua conexão e tente novamente.",
                });
            } finally {
                if (form.isConnected && form.dataset.submitting === "true") {
                    form.dataset.submitting = "false";
                    form.removeAttribute("aria-busy");
                    form.querySelectorAll("button, input").forEach((control) => {
                        control.disabled = false;
                    });
                    submit.textContent = submit.dataset.idleText;
                    if (form.matches("[data-preset-selection-form]")) {
                        submit.disabled = !form.querySelector(
                            'input[name="preset_id"]:checked',
                        );
                    }
                }
            }
        });
    });

    document.querySelectorAll("[data-reorder-list]").forEach((list) => {
        const status = list.parentElement.querySelector("[data-reorder-status]");
        const csrfToken = list.querySelector("[data-csrf-token]")?.value;
        const announce = (message) => {
            if (status) status.textContent = message;
        };
        const persistOrder = async (orderedItems) => {
            const order = orderedItems.map((item) => Number(item.dataset.reorderId));
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
        window.GymNoteSortable.create(list, {
            itemSelector: "[data-reorder-id]",
            onOrderChange: persistOrder,
        });
    });
})();
