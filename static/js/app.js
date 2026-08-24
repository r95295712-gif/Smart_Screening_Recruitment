let activeTaskSubmission = null;
let taskOverlayDelayTimer = null;
const pageStatePrefix = "smart-screening-page-state:";

function currentPageStateKey() {
  return `${pageStatePrefix}${window.location.pathname}${window.location.search}`;
}

function savePageState() {
  const state = {
    x: window.scrollX,
    y: window.scrollY,
    containers: Array.from(document.querySelectorAll(".table-scroll")).map(
      (container) => ({
        left: container.scrollLeft,
        top: container.scrollTop,
      })
    ),
  };
  try {
    sessionStorage.setItem(currentPageStateKey(), JSON.stringify(state));
  } catch (error) {}
}

function restorePageState() {
  let state = null;
  try {
    state = JSON.parse(sessionStorage.getItem(currentPageStateKey()) || "null");
    sessionStorage.removeItem(currentPageStateKey());
  } catch (error) {}
  if (!state) return;
  window.requestAnimationFrame(() => {
    window.scrollTo(state.x || 0, state.y || 0);
    document.querySelectorAll(".table-scroll").forEach((container, index) => {
      const saved = state.containers?.[index];
      if (!saved) return;
      container.scrollLeft = saved.left || 0;
      container.scrollTop = saved.top || 0;
    });
  });
}

function enhanceTables(root = document) {
  root.querySelectorAll("table").forEach((table) => {
    if (table.parentElement?.classList.contains("table-scroll")) return;
    const wrapper = document.createElement("div");
    wrapper.className = "table-scroll";
    table.parentNode.insertBefore(wrapper, table);
    wrapper.appendChild(table);
  });
}

function enhanceRowSelection(root = document) {
  root.querySelectorAll("tbody input[type='checkbox']").forEach((checkbox) => {
    if (checkbox.dataset.rowSelectionReady) return;
    checkbox.dataset.rowSelectionReady = "true";
    const updateRow = () => {
      checkbox.closest("tr")?.classList.toggle("row-selected", checkbox.checked);
    };
    checkbox.addEventListener("change", updateRow);
    updateRow();
  });
  root.querySelectorAll("thead input[type='checkbox']").forEach((checkbox) => {
    if (checkbox.dataset.rowSelectionReady) return;
    checkbox.dataset.rowSelectionReady = "true";
    checkbox.addEventListener("change", () => {
      window.requestAnimationFrame(() => {
        root.querySelectorAll("tbody input[type='checkbox']").forEach((rowCheckbox) => {
          rowCheckbox
            .closest("tr")
            ?.classList.toggle("row-selected", rowCheckbox.checked);
        });
      });
    });
  });
}

function scheduleRegionRefresh(region) {
  if (!region?.dataset.autoRefresh || !region.dataset.refreshRegion) return;
  const delay = Number(region.dataset.autoRefresh || 3000);
  window.setTimeout(async () => {
    if (!document.body.contains(region)) return;
    if (
      document.visibilityState !== "visible" ||
      region.contains(document.activeElement)
    ) {
      scheduleRegionRefresh(region);
      return;
    }
    const scrollX = window.scrollX;
    const scrollY = window.scrollY;
    const containerScroll = Array.from(region.querySelectorAll(".table-scroll")).map(
      (container) => ({
        left: container.scrollLeft,
        top: container.scrollTop,
      })
    );
    try {
      const response = await fetch(window.location.href, {
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      if (!response.ok) throw new Error("refresh failed");
      const nextDocument = new DOMParser().parseFromString(
        await response.text(),
        "text/html"
      );
      const selector = `[data-refresh-region="${CSS.escape(
        region.dataset.refreshRegion
      )}"]`;
      const nextRegion = nextDocument.querySelector(selector);
      if (!nextRegion) return;
      region.replaceWith(nextRegion);
      enhanceTables(nextRegion);
      enhanceRowSelection(nextRegion);
      nextRegion.querySelectorAll(".table-scroll").forEach((container, index) => {
        const saved = containerScroll[index];
        if (!saved) return;
        container.scrollLeft = saved.left;
        container.scrollTop = saved.top;
      });
      window.scrollTo(scrollX, scrollY);
      scheduleRegionRefresh(nextRegion);
    } catch (error) {
      scheduleRegionRefresh(region);
    }
  }, delay);
}

function createOperationId() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (character) => {
    const randomValue = Math.floor(Math.random() * 16);
    const value = character === "x" ? randomValue : (randomValue & 0x3) | 0x8;
    return value.toString(16);
  });
}

function prepareTaskCancellation(form) {
  const cancelUrl = form.dataset.cancelUrl;
  if (!cancelUrl) return null;
  let operationInput = form.querySelector('input[name="operation_id"]');
  if (!operationInput) {
    operationInput = document.createElement("input");
    operationInput.type = "hidden";
    operationInput.name = "operation_id";
    form.appendChild(operationInput);
  }
  operationInput.value = createOperationId();
  return {
    cancelUrl,
    operationId: operationInput.value,
    csrfToken: form.querySelector('input[name="csrfmiddlewaretoken"]')?.value || "",
  };
}

function showTaskOverlay(message, form, cancellation) {
  const overlay = document.querySelector("[data-task-overlay]");
  if (!overlay) return;
  const titleNode = overlay.querySelector("[data-task-overlay-title]");
  const messageNode = overlay.querySelector("[data-task-overlay-message]");
  const cancelButton = overlay.querySelector("[data-task-overlay-cancel]");
  if (titleNode) titleNode.textContent = "正在处理";
  if (messageNode && message) messageNode.textContent = message;
  if (cancelButton) {
    cancelButton.disabled = false;
    cancelButton.textContent = cancellation ? "取消本次操作" : "取消等待";
  }
  overlay.setAttribute("aria-busy", "true");
  overlay.hidden = false;
  document.body.classList.add("task-overlay-open");
  window.clearTimeout(taskOverlayDelayTimer);
  taskOverlayDelayTimer = window.setTimeout(() => {
    if (overlay.hidden) return;
    if (titleNode) titleNode.textContent = "处理时间较长";
    if (messageNode) {
      messageNode.textContent = "您可以继续等待，也可以取消等待并返回当前页面。";
    }
  }, 15000);
  activeTaskSubmission = {
    form,
    cancellation,
    buttons: Array.from(
      form.querySelectorAll("button[type='submit'], input[type='submit']")
    ).map((button) => ({ button, wasDisabled: button.disabled })),
  };
}

function hideTaskOverlay() {
  const overlay = document.querySelector("[data-task-overlay]");
  window.clearTimeout(taskOverlayDelayTimer);
  taskOverlayDelayTimer = null;
  if (overlay) {
    overlay.hidden = true;
    overlay.setAttribute("aria-busy", "false");
  }
  document.body.classList.remove("task-overlay-open");
  activeTaskSubmission?.buttons.forEach(({ button, wasDisabled }) => {
    button.disabled = wasDisabled;
  });
  activeTaskSubmission = null;
}

function showTaskCancellationNotice(cancelRequested) {
  const main = document.querySelector("main");
  if (!main) return;
  let messages = main.querySelector(":scope > .messages");
  if (!messages) {
    messages = document.createElement("div");
    messages.className = "messages";
    main.prepend(messages);
  }
  const notice = document.createElement("div");
  notice.className = "message warning";
  notice.textContent = cancelRequested
    ? "已提交取消请求，本次岗位规则草稿不会保存。"
    : "已停止页面等待。操作如果已经完成，刷新页面后会显示最新结果。";
  messages.prepend(notice);
}

function showInlineFeedback(form, message, ok) {
  const feedback = form.querySelector("[data-form-feedback]");
  if (!feedback) return;
  feedback.textContent = message;
  feedback.classList.toggle("success", ok);
  feedback.classList.toggle("error", !ok);
}

function updateConfigurationState(state, referencePosition) {
  if (!state) return;
  document.querySelectorAll("[data-configuration-state]").forEach((status) => {
    status.textContent = state.label;
    status.classList.toggle(
      "success",
      Boolean(state.can_analyze) && state.code !== "update_required"
    );
    status.classList.toggle("warning", state.code === "update_required");
  });
  const banner = document.querySelector("[data-configuration-banner]");
  const blockers = document.querySelector("[data-configuration-blockers]");
  if (banner) banner.hidden = !state.blockers?.length;
  if (blockers) {
    blockers.textContent = state.blockers?.length
      ? `请完成：${state.blockers.join("、")}`
      : "";
  }
  const referenceJd = document.querySelector("[data-reference-jd]");
  if (referenceJd && referencePosition) {
    referenceJd.textContent = referencePosition.jd || "暂无对应参考内容";
  }
}

async function submitAsyncForm(form, submitter) {
  const buttons = Array.from(
    form.querySelectorAll("button[type='submit'], input[type='submit']")
  );
  const previousLabels = buttons.map((button) => button.textContent);
  buttons.forEach((button) => {
    button.disabled = true;
  });
  if (submitter) submitter.textContent = submitter.dataset.pendingText || "正在保存…";
  showInlineFeedback(form, "", true);

  try {
    const response = await fetch(form.action, {
      method: "POST",
      body: new FormData(form),
      credentials: "same-origin",
      headers: {
        "X-Requested-With": "XMLHttpRequest",
        Accept: "application/json",
      },
    });
    const payload = await response.json();
    showInlineFeedback(form, payload.message || "操作已完成。", response.ok && payload.ok);
    if (response.ok && payload.ok) {
      updateConfigurationState(payload.state, payload.reference_position);
    }
  } catch (error) {
    showInlineFeedback(form, "保存失败，请检查网络后重试。", false);
  } finally {
    buttons.forEach((button, index) => {
      button.disabled = false;
      button.textContent = previousLabels[index];
    });
  }
}

function shouldSubmitPageForm(form) {
  return (
    (form.method || "get").toLowerCase() === "post" &&
    form.dataset.asyncSubmit === undefined &&
    form.dataset.fullSubmit === undefined &&
    form.dataset.loadingText === undefined &&
    form.dataset.cancelUrl === undefined &&
    form.dataset.ruleForm === undefined &&
    !form.enctype.includes("multipart/form-data") &&
    !form.target
  );
}

async function submitPageForm(form, submitter) {
  const action = submitter?.hasAttribute("formaction")
    ? submitter.formAction
    : form.action || window.location.href;
  const payload = new FormData(form);
  if (submitter?.name) payload.set(submitter.name, submitter.value);
  const buttons = Array.from(
    form.querySelectorAll("button[type='submit'], input[type='submit']")
  );
  buttons.forEach((button) => {
    button.disabled = true;
  });
  try {
    const response = await fetch(action, {
      method: "POST",
      body: payload,
      credentials: "same-origin",
      headers: {
        "X-Requested-With": "XMLHttpRequest",
        Accept: "text/html",
      },
    });
    const responseUrl = new URL(response.url, window.location.href);
    if (
      responseUrl.pathname !== window.location.pathname ||
      responseUrl.search !== window.location.search
    ) {
      window.location.assign(responseUrl.href);
      return;
    }
    const nextDocument = new DOMParser().parseFromString(
      await response.text(),
      "text/html"
    );
    const currentMain = document.querySelector("main");
    const nextMain = nextDocument.querySelector("main");
    if (!response.ok || !currentMain || !nextMain) {
      throw new Error("page action failed");
    }
    const scrollX = window.scrollX;
    const scrollY = window.scrollY;
    currentMain.innerHTML = nextMain.innerHTML;
    enhanceTables(currentMain);
    enhanceRowSelection(currentMain);
    currentMain
      .querySelectorAll("[data-auto-refresh][data-refresh-region]")
      .forEach(scheduleRegionRefresh);
    try {
      sessionStorage.removeItem(currentPageStateKey());
    } catch (error) {}
    window.scrollTo(scrollX, scrollY);
  } catch (error) {
    buttons.forEach((button) => {
      button.disabled = false;
    });
    form.dataset.fullSubmit = "true";
    form.requestSubmit(submitter || undefined);
  } finally {
    buttons.forEach((button) => {
      button.disabled = false;
    });
  }
}

document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  if ((form.method || "get").toLowerCase() !== "post") {
    savePageState();
    return;
  }
  if (form.dataset.asyncSubmit !== undefined) {
    event.preventDefault();
    submitAsyncForm(form, event.submitter);
    return;
  }
  savePageState();
  if (shouldSubmitPageForm(form)) {
    event.preventDefault();
    submitPageForm(form, event.submitter);
    return;
  }
  if (form.dataset.noLoading !== undefined) return;

  const submitter = event.submitter;
  const message =
    submitter?.dataset.loadingText ||
    form.dataset.loadingText ||
    "操作正在处理，请稍候，不要关闭页面或重复点击。";
  const cancellation = prepareTaskCancellation(form);
  showTaskOverlay(message, form, cancellation);
  form.querySelectorAll("button[type='submit'], input[type='submit']").forEach((button) => {
    button.disabled = true;
  });
});

document.addEventListener("click", (event) => {
  const backButton = event.target.closest("[data-back-button]");
  if (backButton) {
    const fallbackUrl = backButton.dataset.fallbackUrl || "/";
    window.location.assign(fallbackUrl);
    return;
  }
  const cancelButton = event.target.closest("[data-task-overlay-cancel]");
  if (!cancelButton || !activeTaskSubmission) return;
  cancelButton.disabled = true;
  const { cancellation } = activeTaskSubmission;
  if (cancellation) {
    const payload = new FormData();
    payload.set("operation_id", cancellation.operationId);
    payload.set("csrfmiddlewaretoken", cancellation.csrfToken);
    const sent = navigator.sendBeacon?.(cancellation.cancelUrl, payload);
    if (!sent) {
      fetch(cancellation.cancelUrl, {
        method: "POST",
        body: payload,
        credentials: "same-origin",
        keepalive: true,
      }).catch(() => {});
    }
  }
  hideTaskOverlay();
  window.stop();
  showTaskCancellationNotice(Boolean(cancellation));
});

window.addEventListener("pageshow", () => hideTaskOverlay());

document.addEventListener("DOMContentLoaded", () => {
  const themeOrder = ["system", "light", "dark"];
  const themeLabels = {
    system: "跟随系统",
    light: "浅色模式",
    dark: "深色模式",
  };
  const storedTheme = (() => {
    try {
      return localStorage.getItem("smart-screening-theme") || "light";
    } catch (error) {
      return "light";
    }
  })();
  let currentTheme = themeOrder.includes(storedTheme) ? storedTheme : "system";

  const applyTheme = (theme) => {
    currentTheme = theme;
    if (theme === "system") {
      delete document.documentElement.dataset.theme;
    } else {
      document.documentElement.dataset.theme = theme;
    }
    try {
      localStorage.setItem("smart-screening-theme", theme);
    } catch (error) {}
    document.querySelectorAll("[data-theme-label]").forEach((label) => {
      label.textContent = themeLabels[theme];
    });
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.dataset.themeState = theme;
      button.setAttribute("aria-label", `当前为${themeLabels[theme]}，点击切换`);
    });
  };

  document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const nextIndex = (themeOrder.indexOf(currentTheme) + 1) % themeOrder.length;
      applyTheme(themeOrder[nextIndex]);
    });
  });
  applyTheme(currentTheme);

  const mobileToggle = document.querySelector("[data-mobile-nav-toggle]");
  const sidebar = document.querySelector(".sidebar");
  if (mobileToggle && sidebar) {
    mobileToggle.addEventListener("click", () => {
      const isOpen = sidebar.classList.toggle("nav-open");
      mobileToggle.setAttribute("aria-expanded", String(isOpen));
      mobileToggle.setAttribute("aria-label", isOpen ? "收起导航" : "展开导航");
    });
  }

  enhanceTables();
  enhanceRowSelection();
  restorePageState();

  document.querySelectorAll("[data-rule-form]").forEach((form) => {
    const editors = [];
    form.querySelectorAll("[data-rule-editor]").forEach((editor) => {
      const hiddenInput = document.getElementById(editor.dataset.inputId);
      const rowsContainer = editor.querySelector("[data-rule-rows]");
      const template = editor.querySelector("[data-rule-template]");
      const addButton = editor.querySelector("[data-add-rule-item]");
      const weightTotal = editor.querySelector("[data-weight-total]");
      if (!hiddenInput || !rowsContainer || !template) return;

      const updateWeightTotal = () => {
        if (!weightTotal) return;
        const total = Array.from(
          rowsContainer.querySelectorAll('[data-rule-key="weight"]')
        ).reduce((sum, input) => sum + (Number(input.value) || 0), 0);
        weightTotal.textContent = String(total);
        weightTotal.closest(".weight-summary")?.classList.toggle("valid", total === 100);
      };

      const updateRowTitle = (row) => {
        const nameInput = row.querySelector('[data-rule-key="name"]');
        const title = row.querySelector("[data-row-title]");
        if (title && nameInput) {
          title.textContent = nameInput.value.trim() || title.dataset.defaultTitle || title.textContent;
        }
      };

      const addRow = (item = {}) => {
        const fragment = template.content.cloneNode(true);
        const row = fragment.querySelector(".rule-item-card");
        const title = row.querySelector("[data-row-title]");
        if (title) title.dataset.defaultTitle = title.textContent;
        row.querySelectorAll("[data-rule-key]").forEach((input) => {
          const key = input.dataset.ruleKey;
          input.value = item[key] ?? "";
          input.addEventListener("input", () => {
            updateRowTitle(row);
            updateWeightTotal();
          });
        });
        row.querySelector("[data-remove-rule-item]")?.addEventListener("click", () => {
          row.remove();
          updateWeightTotal();
        });
        rowsContainer.appendChild(fragment);
        updateRowTitle(rowsContainer.lastElementChild);
        updateWeightTotal();
      };

      let initialItems = [];
      try {
        initialItems = JSON.parse(hiddenInput.value || "[]");
      } catch (error) {
        initialItems = [];
      }
      if (!Array.isArray(initialItems)) initialItems = [];
      initialItems.forEach((item) => addRow(item));
      if (!initialItems.length) addRow();
      addButton?.addEventListener("click", () => addRow());

      const serialize = () => {
        const items = Array.from(rowsContainer.querySelectorAll(".rule-item-card"))
          .map((row) => {
            const item = {};
            row.querySelectorAll("[data-rule-key]").forEach((input) => {
              const key = input.dataset.ruleKey;
              item[key] = key === "weight" ? Number(input.value) || 0 : input.value.trim();
            });
            return item;
          })
          .filter((item) => item.name || item.description);
        hiddenInput.value = JSON.stringify(items);
      };
      editors.push({ serialize, updateWeightTotal });
    });

    form.addEventListener("submit", () => {
      editors.forEach(({ serialize }) => serialize());
    });
  });

  document.querySelectorAll("[data-auto-refresh][data-refresh-region]").forEach(
    scheduleRegionRefresh
  );
});
