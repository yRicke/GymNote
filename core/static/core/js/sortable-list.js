(() => {
    const DEFAULT_ACTIVATION_DISTANCE = 5;
    const EDGE_SIZE = 72;
    const MAX_SCROLL_SPEED = 14;

    const scrollContainerFor = (element) => {
        let parent = element.parentElement;
        while (parent && parent !== document.body) {
            const style = window.getComputedStyle(parent);
            const scrollable = /(auto|scroll)/.test(style.overflowY)
                && parent.scrollHeight > parent.clientHeight;
            if (scrollable) return parent;
            parent = parent.parentElement;
        }
        return window;
    };

    class SortableList {
        constructor(list, {
            itemSelector,
            handleSelector = ".drag-handle",
            activationDistance = DEFAULT_ACTIVATION_DISTANCE,
            onChange = () => {},
        }) {
            this.list = list;
            this.itemSelector = itemSelector;
            this.handleSelector = handleSelector;
            this.activationDistance = activationDistance;
            this.onChange = onChange;
            this.pointer = null;
            this.drag = null;
            this.autoScrollFrame = null;
            this.autoScrollSpeed = 0;
            this.scrollContainer = scrollContainerFor(list);

            this.onPointerDown = this.onPointerDown.bind(this);
            this.onPointerMove = this.onPointerMove.bind(this);
            this.onPointerUp = this.onPointerUp.bind(this);
            this.onPointerCancel = this.onPointerCancel.bind(this);
            this.onKeyDown = this.onKeyDown.bind(this);
            this.preventNativeInteraction = this.preventNativeInteraction.bind(this);
            this.tickAutoScroll = this.tickAutoScroll.bind(this);

            this.list.addEventListener("pointerdown", this.onPointerDown);
            window.addEventListener("pointermove", this.onPointerMove, { passive: false });
            window.addEventListener("pointerup", this.onPointerUp, { passive: false });
            window.addEventListener("pointercancel", this.onPointerCancel);
            this.list.addEventListener("keydown", this.onKeyDown);
            this.list.addEventListener("contextmenu", this.preventNativeInteraction);
            this.list.addEventListener("selectstart", this.preventNativeInteraction);
            this.list.addEventListener("dragstart", this.preventNativeInteraction);
            this.refresh();
        }

        items() {
            return [...this.list.children].filter((item) => item.matches(this.itemSelector));
        }

        refresh() {
            this.items().forEach((item) => {
                item.draggable = false;
            });
        }

        preventNativeInteraction(event) {
            if (event.type === "dragstart" || event.target.closest(this.handleSelector)) {
                event.preventDefault();
            }
        }

        onPointerDown(event) {
            const handle = event.target.closest(this.handleSelector);
            if (!handle || this.pointer || this.drag) return;
            if (event.pointerType === "mouse" && event.button !== 0) return;
            const item = handle.closest(this.itemSelector);
            if (!item || item.parentElement !== this.list) return;

            event.preventDefault();
            this.pointer = {
                id: event.pointerId,
                type: event.pointerType || "pointer",
                startX: event.clientX,
                startY: event.clientY,
                lastX: event.clientX,
                lastY: event.clientY,
                item,
                handle,
            };
            item.classList.add("is-sort-pending");
        }

        onPointerMove(event) {
            if (!this.pointer || event.pointerId !== this.pointer.id) return;
            event.preventDefault();
            this.pointer.lastX = event.clientX;
            this.pointer.lastY = event.clientY;

            if (!this.drag) {
                const distance = Math.hypot(
                    event.clientX - this.pointer.startX,
                    event.clientY - this.pointer.startY,
                );
                if (distance < this.activationDistance) return;
                this.beginDrag();
            }

            this.positionFloatingItem(event.clientY);
            this.positionPlaceholder(event.clientY);
            this.updateAutoScroll(event.clientY);
        }

        onPointerUp(event) {
            if (!this.pointer || event.pointerId !== this.pointer.id) return;
            event.preventDefault();
            if (this.drag) this.finishDrag(true, this.pointer.type);
            else this.clearPointer();
        }

        onPointerCancel(event) {
            if (!this.pointer || event.pointerId !== this.pointer.id) return;
            if (this.drag) this.finishDrag(false, this.pointer.type);
            else this.clearPointer();
        }

        onKeyDown(event) {
            if (!["ArrowUp", "ArrowDown"].includes(event.key)) return;
            const handle = event.target.closest(this.handleSelector);
            const item = handle?.closest(this.itemSelector);
            if (!item || item.parentElement !== this.list) return;
            const items = this.items();
            const currentIndex = items.indexOf(item);
            const nextIndex = currentIndex + (event.key === "ArrowUp" ? -1 : 1);
            if (nextIndex < 0 || nextIndex >= items.length) return;

            event.preventDefault();
            if (nextIndex < currentIndex) this.list.insertBefore(item, items[nextIndex]);
            else this.list.insertBefore(item, items[nextIndex].nextSibling);
            handle.focus({ preventScroll: true });
            this.onChange(this.items(), item, "keyboard");
        }

        beginDrag() {
            const { item } = this.pointer;
            const rect = item.getBoundingClientRect();
            const originalItems = this.items();
            const preview = item.cloneNode(true);
            preview.removeAttribute("data-reorder-id");
            preview.removeAttribute("data-selected-exercise-id");
            preview.setAttribute("aria-hidden", "true");
            preview.inert = true;

            this.drag = {
                item,
                preview,
                originalIndex: originalItems.indexOf(item),
                offsetY: this.pointer.startY - rect.top,
                height: rect.height,
            };
            item.classList.remove("is-sort-pending");
            item.classList.add("sortable-placeholder");
            document.body.append(preview);
            preview.classList.remove("sortable-placeholder");
            preview.classList.add("sortable-dragging");
            preview.style.width = `${rect.width}px`;
            preview.style.height = `${rect.height}px`;
            preview.style.left = `${rect.left}px`;
            preview.style.top = `${rect.top}px`;
            document.body.classList.add("is-reordering");
            this.list.classList.add("is-reordering");
        }

        positionFloatingItem(clientY) {
            if (!this.drag) return;
            this.drag.preview.style.top = `${clientY - this.drag.offsetY}px`;
        }

        positionPlaceholder(clientY) {
            if (!this.drag) return;
            const floatingCenter = clientY - this.drag.offsetY + this.drag.height / 2;
            const candidates = this.items().filter((item) => item !== this.drag.item);
            const before = candidates.find((item) => {
                const rect = item.getBoundingClientRect();
                return floatingCenter < rect.top + rect.height / 2;
            });
            if (before) this.list.insertBefore(this.drag.item, before);
            else this.list.append(this.drag.item);
        }

        updateAutoScroll(clientY) {
            const bounds = this.scrollContainer === window
                ? { top: 0, bottom: window.innerHeight }
                : this.scrollContainer.getBoundingClientRect();
            const topDistance = clientY - bounds.top;
            const bottomDistance = bounds.bottom - clientY;
            if (topDistance < EDGE_SIZE) {
                this.autoScrollSpeed = -MAX_SCROLL_SPEED * (1 - Math.max(0, topDistance) / EDGE_SIZE);
            } else if (bottomDistance < EDGE_SIZE) {
                this.autoScrollSpeed = MAX_SCROLL_SPEED * (1 - Math.max(0, bottomDistance) / EDGE_SIZE);
            } else {
                this.autoScrollSpeed = 0;
            }

            if (this.autoScrollSpeed && !this.autoScrollFrame) {
                this.autoScrollFrame = window.requestAnimationFrame(this.tickAutoScroll);
            }
        }

        tickAutoScroll() {
            this.autoScrollFrame = null;
            if (!this.drag || !this.autoScrollSpeed || !this.pointer) return;
            this.scrollContainer.scrollBy({ top: this.autoScrollSpeed, behavior: "auto" });
            this.positionPlaceholder(this.pointer.lastY);
            this.autoScrollFrame = window.requestAnimationFrame(this.tickAutoScroll);
        }

        finishDrag(commit, inputMethod) {
            const { item, preview, originalIndex } = this.drag;
            this.stopAutoScroll();

            if (!commit) {
                item.remove();
                const remainingItems = this.items();
                if (originalIndex >= remainingItems.length) this.list.append(item);
                else this.list.insertBefore(item, remainingItems[originalIndex]);
            }
            preview.remove();
            item.classList.remove("sortable-placeholder");
            document.body.classList.remove("is-reordering");
            this.list.classList.remove("is-reordering");
            const changed = originalIndex !== this.items().indexOf(item);
            this.drag = null;
            this.clearPointer();
            if (commit && changed) this.onChange(this.items(), item, inputMethod);
        }

        clearPointer() {
            if (!this.pointer) return;
            const pointer = this.pointer;
            this.pointer = null;
            pointer.item.classList.remove("is-sort-pending");
        }

        stopAutoScroll() {
            this.autoScrollSpeed = 0;
            if (this.autoScrollFrame) window.cancelAnimationFrame(this.autoScrollFrame);
            this.autoScrollFrame = null;
        }
    }

    window.GymNoteSortable = {
        create(list, options) {
            return new SortableList(list, options);
        },
    };
})();
