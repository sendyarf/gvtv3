// Constants for API URLs
const CHANNELS_API_URL = "https://govoet.pages.dev/channels.json";
const EVENTS_API_URL = "https://weekendsch.pages.dev/sch/schedulegvt.json";

// Global object to store countdown intervals
let countdownIntervals = {};
// Tracks the currently active event ID
let activeEventId = null;
// Store event end timers
let eventEndTimers = {};

// DOM Cache
const domCache = {
  liveEventContent: null,
  liveTvContent: null,
  videoCountdownContainer: null,
  videoCountdownTimer: null,
  videoIframe: null,
  videoPlaceholder: null,
};

// Initialize DOM Cache
function initDomCache() {
  domCache.liveEventContent = document.querySelector("#live-event #content");
  domCache.liveTvContent = document.querySelector("#live-tv #content");
  domCache.videoCountdownContainer = document.getElementById("video-countdown");
  domCache.videoCountdownTimer =
    domCache.videoCountdownContainer?.querySelector(".countdown-timer");
  domCache.videoIframe = document.getElementById("video-iframe");
  domCache.videoPlaceholder = document.getElementById("video-placeholder");
}

// Improved timezone conversion function
function parseEventDateTime(dateStr, timeStr) {
  if (!dateStr || !timeStr) {
    console.error("Invalid date or time:", dateStr, timeStr);
    return new Date();
  }

  // Parse as Jakarta time (UTC+7)
  const jakartaTimeString = `${dateStr}T${timeStr}:00+07:00`;
  const jakartaTime = new Date(jakartaTimeString);

  // Convert to user's local time
  const userTime = new Date(jakartaTime.getTime());

  console.log(
    `Timezone conversion - Jakarta: ${jakartaTimeString}, Local: ${userTime}`
  );
  return userTime;
}

// Improved function to check event status
function getEventStatus(event) {
  if (!event.match_date || !event.match_time) {
    return { isEnded: true };
  }

  try {
    const matchDateTime = parseEventDateTime(
      event.match_date,
      event.match_time
    );
    const duration = parseFloat(event.duration) || 3.5;
    const durationMs = duration * 60 * 60 * 1000;
    const endTime = new Date(matchDateTime.getTime() + durationMs);
    const now = new Date();

    return {
      isLive: now >= matchDateTime && now < endTime,
      isEnded: now >= endTime,
      isFuture: now < matchDateTime,
      matchDateTime: matchDateTime,
      endTime: endTime,
      timeUntilStart: matchDateTime - now,
      timeUntilEnd: endTime - now,
    };
  } catch (error) {
    console.error("Error checking event status:", error);
    return { isEnded: true };
  }
}

// Function to hide event when duration is completed
function hideEvent(eventId) {
  const eventContainer = document.querySelector(
    `.event-container[data-id="${eventId}"]`
  );
  if (eventContainer) {
    // Add fade out animation
    eventContainer.style.transition =
      "opacity 0.5s ease, max-height 0.5s ease, margin 0.5s ease, padding 0.5s ease";
    eventContainer.style.opacity = "0";
    eventContainer.style.maxHeight = "0";
    eventContainer.style.overflow = "hidden";
    eventContainer.style.margin = "0";
    eventContainer.style.padding = "0";

    setTimeout(() => {
      if (eventContainer.parentNode) {
        eventContainer.parentNode.removeChild(eventContainer);
      }
      sessionStorage.setItem(`eventStatus_${eventId}`, "ended");
      console.log(`🗑️ Event ${eventId} hidden after duration completed`);

      // Check if no events left
      checkNoEventsMessage();
    }, 500);
  }
}

// Check and show no events message
function checkNoEventsMessage() {
  if (!domCache.liveEventContent)
    domCache.liveEventContent = document.querySelector("#live-event #content");
  const liveEventContent = domCache.liveEventContent;
  if (!liveEventContent) return;

  const visibleEvents = liveEventContent.querySelectorAll(
    '.event-container[style*="display: block"], .event-container:not([style])'
  );

  if (visibleEvents.length === 0) {
    if (!liveEventContent.querySelector(".no-events-message")) {
      liveEventContent.innerHTML = `
                <div class="no-events-message">
                    <div class="message-icon">
                        <i class="fas fa-calendar-times"></i>
                    </div>
                    <h3>No Schedule Available</h3>
                    <p>All events have ended. Please check back later for new schedules.</p>
                    <button id="refresh-button" class="refresh-button">
                        <i class="fas fa-sync-alt"></i> Refresh Page
                    </button>
                </div>
            `;

      document
        .getElementById("refresh-button")
        ?.addEventListener("click", () => {
          location.reload();
        });
    }
  }
}

// Loads channel data from channels.json
async function loadChannels() {
  try {
    console.log("🔄 Loading channels...");

    // Skeleton loading is already in HTML, we just need to replace content when loaded

    const response = await fetch(CHANNELS_API_URL);
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const channels = await response.json();

    if (!domCache.liveTvContent)
      domCache.liveTvContent = document.querySelector("#live-tv #content");
    const liveTvContent = domCache.liveTvContent;

    if (!liveTvContent) throw new Error("Live TV content element not found");

    liveTvContent.innerHTML = "";

    if (channels && channels.length > 0) {
      channels.forEach((channel) => {
        const channelHtml = `
                    <div class="channel-container" data-id="${channel.id}" data-url="${channel.url}">
                        <div class="logo-container">
                            <img src="${channel.logo}" alt="Channel Logo" class="logo" loading="lazy" onerror="this.src='https://placehold.co/50x50/png?text=Channel'">
                        </div>
                        <div class="info-container">
                            <h3 class="channel-name">${channel.name}</h3>
                            <p class="status">${channel.status}</p>
                        </div>
                    </div>
                `;
        liveTvContent.insertAdjacentHTML("beforeend", channelHtml);
      });
      liveTvContent.insertAdjacentHTML(
        "beforeend",
        '<div class="spacer"></div>'
      );

      setupChannels();
      console.log(`✅ ${channels.length} channels loaded successfully`);
    } else {
      liveTvContent.innerHTML = `
                <div class="no-events-message">
                    <div class="message-icon">
                        <i class="fas fa-tv"></i>
                    </div>
                    <h3>No Channels Available</h3>
                    <p>Please check back later for channel updates.</p>
                </div>
            `;
      console.log("ℹ️ No channels available");
    }
  } catch (error) {
    console.error("❌ Error loading channels:", error);

    // Tampilkan error message
    const liveTvContent = document.querySelector("#live-tv #content");
    if (liveTvContent) {
      liveTvContent.innerHTML = `
                <div class="no-events-message">
                    <div class="message-icon">
                        <i class="fas fa-exclamation-triangle"></i>
                    </div>
                    <h3>Failed to Load Channels</h3>
                    <p>Please check your connection and refresh the page.</p>
                    <button class="refresh-button" onclick="location.reload()">
                        <i class="fas fa-sync-alt"></i> Refresh
                    </button>
                </div>
            `;
    }
  }
}

// Format date and time for display in user's timezone
function formatDateTimeForDisplay(dateStr, timeStr) {
  try {
    const eventDateTime = parseEventDateTime(dateStr, timeStr);

    return {
      date: eventDateTime.toLocaleDateString("en-US", {
        year: "numeric",
        month: "short",
        day: "numeric",
      }),
      time: eventDateTime.toLocaleTimeString("en-US", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }),
    };
  } catch (error) {
    console.error("Error formatting date/time:", error);
    return {
      date: dateStr,
      time: timeStr,
    };
  }
}

// Loads event data from event.json with improved filtering and sorting
async function loadEvents() {
  try {
    console.log("🔄 Loading events...");

    const response = await fetch(EVENTS_API_URL);
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    const events = await response.json();

    if (!domCache.liveEventContent)
      domCache.liveEventContent = document.querySelector(
        "#live-event #content"
      );
    const liveEventContent = domCache.liveEventContent;

    if (!liveEventContent)
      throw new Error("Live event content element not found");

    liveEventContent.innerHTML = "";

    // Filter out invalid events
    const validEvents = events.filter((event) => {
      // Skip events with invalid fields
      if (!event.id || !event.league || !event.team1 || !event.team2) {
        console.log(`🚫 Event skipped - missing required fields:`, event.id);
        return false;
      }

      const hasInvalidFields =
        event.kickoff_date === "live" ||
        event.kickoff_time === "live" ||
        event.match_date === "live" ||
        event.match_time === "live" ||
        event.duration === "live";

      if (hasInvalidFields) {
        console.log(
          `🚫 Event ${event.id} has invalid fields and will not be rendered`
        );
        return false;
      }

      return true;
    });

    console.log(
      `📊 Total events: ${events.length}, Valid events: ${validEvents.length}`
    );

    if (validEvents.length === 0) {
      liveEventContent.innerHTML = `
                <div class="no-events-message">
                    <div class="message-icon">
                        <i class="fas fa-calendar-times"></i>
                    </div>
                    <h3>No Schedule Available</h3>
                    <p>Please refresh the page to check for updates.</p>
                    <button class="refresh-button" onclick="location.reload()">
                        <i class="fas fa-sync-alt"></i> Refresh Page
                    </button>
                </div>
            `;
      return;
    }

    // Sort events: live first, then by the nearest start time
    const sortedEvents = validEvents.slice().sort((a, b) => {
      try {
        const statusA = getEventStatus(a);
        const statusB = getEventStatus(b);

        // Live events first
        if (statusA.isLive && !statusB.isLive) return -1;
        if (!statusA.isLive && statusB.isLive) return 1;

        // Then by start time (soonest first)
        return statusA.matchDateTime - statusB.matchDateTime;
      } catch (error) {
        console.error("Error sorting events:", error);
        return 0;
      }
    });

    let renderedEvents = 0;

    sortedEvents.forEach((event) => {
      try {
        const eventStatus = getEventStatus(event);

        // Skip ended events immediately
        if (eventStatus.isEnded) {
          console.log(
            `⏹️ Event ${event.id} has ended and will not be rendered`
          );
          sessionStorage.setItem(`eventStatus_${event.id}`, "ended");
          return;
        }

        const validServers =
          event.servers?.filter(
            (server) => server.url && server.label && server.label.trim() !== ""
          ) || [];
        const defaultServerUrl = validServers[0]?.url || "";
        const serverListJson = encodeURIComponent(JSON.stringify(validServers));

        const formattedKickoff = formatDateTimeForDisplay(
          event.kickoff_date,
          event.kickoff_time
        );

        const eventHtml = `
                    <div class="event-container" data-id="${event.id}" data-url="${defaultServerUrl}" data-servers="${serverListJson}" data-duration="${event.duration}">
                        <div class="event-header">
                            <div class="league-info">
                                <img src="${event.icon}" class="sport-icon" loading="lazy" onerror="this.style.display='none'">
                                <span class="league-name">${event.league}</span>
                            </div>
                            <button class="copy-url-button" data-id="${event.id}" title="Copy event URL">
                                <i class="fa-solid fa-copy"></i>
                            </button>
                        </div>
                        <div class="event-details">
                            <div class="team-left">
                                <img src="${event.team1.logo}" class="team-logo" alt="${event.team1.name}" loading="lazy" onerror="this.src='https://placehold.co/50x50/png?text=Team'">
                                <span class="team-name">${event.team1.name}</span>
                            </div>
                            <div class="match-info">
                                <div class="kickoff-match-date">${formattedKickoff.date}</div>
                                <div class="kickoff-match-time">${formattedKickoff.time}</div>
                                <div class="live-label" style="display:none;">LIVE</div>
                                <div class="match-date" data-original-date="${event.match_date}" style="display:none;">${event.match_date}</div>
                                <div class="match-time" data-original-time="${event.match_time}" style="display:none;">${event.match_time}</div>
                            </div>
                            <div class="team-right">
                                <img src="${event.team2.logo}" class="team-logo" alt="${event.team2.name}" loading="lazy" onerror="this.src='https://placehold.co/50x50/png?text=Team'">
                                <span class="team-name">${event.team2.name}</span>
                            </div>
                        </div>
                        <div class="server-buttons" style="display:none;">
                            <div class="buttons-container"></div>
                        </div>
                    </div>
                `;
        liveEventContent.insertAdjacentHTML("beforeend", eventHtml);
        console.log(
          `🎯 Event Created: ${event.id} - Status: ${
            eventStatus.isLive ? "LIVE" : "FUTURE"
          }`
        );

        const eventContainer = liveEventContent.querySelector(
          `.event-container[data-id="${event.id}"]`
        );
        const buttonsContainer =
          eventContainer.querySelector(".buttons-container");

        if (!buttonsContainer) {
          console.error(`❌ Buttons container not found for event ${event.id}`);
          return;
        }

        validServers.forEach((server, index) => {
          const button = document.createElement("div");
          button.className = "server-button";
          if (index === 0) button.classList.add("active");
          button.setAttribute("data-url", server.url);
          button.textContent = server.label;
          buttonsContainer.appendChild(button);
          console.log(
            `🔘 Server button created for ${event.id}: ${server.label}`
          );
        });

        // Initialize event state
        initializeEventState(eventContainer, event);
        renderedEvents++;
      } catch (error) {
        console.error(`❌ Error rendering event ${event.id}:`, error);
      }
    });

    if (renderedEvents > 0) {
      liveEventContent.insertAdjacentHTML(
        "beforeend",
        '<div class="spacer"></div>'
      );
      setupEvents();
      setupCopyButtons();
      console.log(`✅ ${renderedEvents} events loaded successfully`);
    } else {
      liveEventContent.innerHTML = `
                <div class="no-events-message">
                    <div class="message-icon">
                        <i class="fas fa-calendar-times"></i>
                    </div>
                    <h3>No Active Events</h3>
                    <p>All events have ended or are not available yet.</p>
                    <button class="refresh-button" onclick="location.reload()">
                        <i class="fas fa-sync-alt"></i> Refresh Page
                    </button>
                </div>
            `;
    }

    // Handle saved events and URL-based loading
    initializeEventStates();
  } catch (error) {
    console.error("❌ Error loading events:", error);

    // Tampilkan error message
    const liveEventContent = document.querySelector("#live-event #content");
    if (liveEventContent) {
      liveEventContent.innerHTML = `
                <div class="no-events-message">
                    <div class="message-icon">
                        <i class="fas fa-exclamation-triangle"></i>
                    </div>
                    <h3>Failed to Load Events</h3>
                    <p>Please check your connection and refresh the page.</p>
                    <button class="refresh-button" onclick="location.reload()">
                        <i class="fas fa-sync-alt"></i> Refresh
                    </button>
                </div>
            `;
    }
  }
}

// Initialize individual event state
function initializeEventState(container, event) {
  try {
    const eventStatus = getEventStatus(event);
    const liveLabel = container.querySelector(".live-label");

    if (eventStatus.isLive) {
      // Event is live - show live label
      liveLabel.style.display = "block";

      // Schedule hiding when duration ends
      if (eventStatus.timeUntilEnd > 0) {
        eventEndTimers[event.id] = setTimeout(() => {
          hideEvent(event.id);
        }, eventStatus.timeUntilEnd);
      }

      console.log(
        `🔴 Event ${event.id} is LIVE - will end in ${Math.round(
          eventStatus.timeUntilEnd / 60000
        )} minutes`
      );
    } else if (eventStatus.isFuture) {
      // Event is in future - hide live label
      liveLabel.style.display = "none";
      console.log(
        `⏰ Event ${event.id} starts in ${Math.round(
          eventStatus.timeUntilStart / 60000
        )} minutes`
      );
    } else {
      // Event has ended - hide immediately
      hideEvent(event.id);
    }
  } catch (error) {
    console.error(`Error initializing event state for ${event.id}:`, error);
  }
}

// Initialize event states from sessionStorage and URL
function initializeEventStates() {
  try {
    const savedEventId = sessionStorage.getItem("activeEventId");
    const savedServerUrl = sessionStorage.getItem(
      `activeServerUrl_${savedEventId}`
    );

    if (savedEventId && savedServerUrl) {
      const eventContainer = document.querySelector(
        `.event-container[data-id="${savedEventId}"]`
      );
      if (eventContainer) {
        const serverButton = eventContainer.querySelector(
          `.server-button[data-url="${savedServerUrl}"]`
        );
        if (serverButton) selectServerButton(serverButton);
        loadEventVideo(eventContainer, savedServerUrl, false);
        const matchDate = eventContainer
          .querySelector(".match-date")
          ?.getAttribute("data-original-date");
        const matchTime = eventContainer
          .querySelector(".match-time")
          ?.getAttribute("data-original-time");
        const matchDateTime = parseEventDateTime(matchDate, matchTime);
        if (new Date() >= matchDateTime) {
          toggleServerButtons(eventContainer, true);
          console.log(
            `Restored server buttons for saved event ${savedEventId}`
          );
        }
      }
    }

    // Handle URL-based event loading
    const path = window.location.pathname;
    const eventIdFromUrl = path.replace(/^\/+/, "");
    console.log("Event ID from URL:", eventIdFromUrl);

    if (eventIdFromUrl) {
      const eventContainer = document.querySelector(
        `.event-container[data-id="${eventIdFromUrl}"]`
      );
      if (eventContainer) {
        const savedServerUrl = sessionStorage.getItem(
          `activeServerUrl_${eventIdFromUrl}`
        );
        const defaultServerUrl = eventContainer.getAttribute("data-url");
        const videoUrl = savedServerUrl || defaultServerUrl;
        const serverButton = eventContainer.querySelector(
          `.server-button[data-url="${videoUrl}"]`
        );
        if (serverButton) selectServerButton(serverButton);
        loadEventVideo(eventContainer, videoUrl, false);

        const matchDate = eventContainer
          .querySelector(".match-date")
          ?.getAttribute("data-original-date");
        const matchTime = eventContainer
          .querySelector(".match-time")
          ?.getAttribute("data-original-time");
        if (matchDate && matchTime) {
          const matchDateTime = parseEventDateTime(matchDate, matchTime);
          if (new Date() >= matchDateTime) {
            toggleServerButtons(eventContainer, true);
            console.log(
              `Showing server buttons for URL-loaded event ${eventIdFromUrl}`
            );
          }
        }

        sessionStorage.setItem("activeEventId", eventIdFromUrl);
        sessionStorage.removeItem("activeChannelId");
        setActiveHoverEffect(eventIdFromUrl);
        switchContent("live-event");
      } else {
        console.warn(`No event found for ID: ${eventIdFromUrl}`);
      }
    }
  } catch (error) {
    console.error("Error initializing event states:", error);
  }
}

// Sets up event listeners for copy buttons
function setupCopyButtons() {
  const copyButtons = document.querySelectorAll(".copy-url-button");
  console.log("Copy Buttons Found:", copyButtons.length);
  copyButtons.forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const eventId = button.getAttribute("data-id");
      const eventUrl = `${window.location.origin}/${eventId}`;
      navigator.clipboard
        .writeText(eventUrl)
        .then(() => {
          console.log(`Copied URL for event ${eventId}: ${eventUrl}`);
          const icon = button.querySelector("i");
          icon.classList.remove("fa-copy");
          icon.classList.add("fa-check");
          setTimeout(() => {
            icon.classList.remove("fa-check");
            icon.classList.add("fa-copy");
          }, 2000);
        })
        .catch((err) => {
          console.error(`Failed to copy URL for event ${eventId}:`, err);
        });
    });
  });
}

// Checks if the device is mobile
function isMobileDevice() {
  return /Mobi|Android/i.test(navigator.userAgent);
}

// Sets up event listeners for event containers
function setupEvents() {
  const eventContainers = document.querySelectorAll(".event-container");
  console.log("Event Containers Found:", eventContainers.length);

  eventContainers.forEach((container) => {
    const eventId = container.getAttribute("data-id");

    const eventStatus = sessionStorage.getItem(`eventStatus_${eventId}`);
    if (eventStatus === "ended") {
      markEventAsEnded(eventId);
      if (activeEventId === eventId) redirectToEndedURL();
    }

    let servers;
    try {
      const serverData = decodeURIComponent(
        container.getAttribute("data-servers")
      );
      servers = JSON.parse(serverData);
    } catch (e) {
      console.error(`Error parsing servers for event ${eventId}:`, e);
      servers = [];
    }

    const buttonsContainer = container.querySelector(".buttons-container");
    if (buttonsContainer) {
      const existingButtons =
        buttonsContainer.querySelectorAll(".server-button");
      existingButtons.forEach((button, index) => {
        if (
          servers[index] &&
          servers[index].label.includes("Mobile") &&
          !isMobileDevice()
        ) {
          button.style.display = "none";
          return;
        }
        button.style.display = "";
        const newButton = button.cloneNode(true);
        button.parentNode.replaceChild(newButton, button);
        newButton.addEventListener("click", (event) => {
          event.stopPropagation();
          selectServerButton(newButton);
          loadEventVideo(container, newButton.getAttribute("data-url"));
          console.log(
            `Server selected for ${eventId}: ${
              newButton.textContent
            } (${newButton.getAttribute("data-url")})`
          );
        });
        if (index === 0) newButton.classList.add("active");
      });
    }

    container.addEventListener("click", () => {
      const now = new Date();
      document
        .querySelectorAll(".event-container .server-buttons")
        .forEach((buttons) => {
          buttons.style.display = "none";
        });

      // Check if event is live to show server buttons
      const matchDate = container
        .querySelector(".match-date")
        ?.getAttribute("data-original-date");
      const matchTime = container
        .querySelector(".match-time")
        ?.getAttribute("data-original-time");
      if (matchDate && matchTime) {
        const matchDateTime = parseEventDateTime(matchDate, matchTime);
        if (now >= matchDateTime) {
          toggleServerButtons(container, true);
        }
      }

      loadEventVideo(container);
    });

    const savedEventId = sessionStorage.getItem("activeEventId");
    const savedServerUrl = sessionStorage.getItem(`activeServerUrl_${eventId}`);
    if (savedEventId === eventId && savedServerUrl) {
      const serverButton = container.querySelector(
        `.server-button[data-url="${savedServerUrl}"]`
      );
      if (serverButton) {
        selectServerButton(serverButton);
        loadEventVideo(container, savedServerUrl, false);

        const matchDate = container
          .querySelector(".match-date")
          ?.getAttribute("data-original-date");
        const matchTime = container
          .querySelector(".match-time")
          ?.getAttribute("data-original-time");
        if (matchDate && matchTime) {
          const matchDateTime = parseEventDateTime(matchDate, matchTime);
          if (new Date() >= matchDateTime) {
            toggleServerButtons(container, true);
            console.log(`Restored server buttons for saved event ${eventId}`);
          }
        }
      }
    }
  });

  startPeriodicEventCheck();
}

// Updates the countdown timer in video container
function updateCountdown(
  videoCountdownContainer,
  videoCountdownTimer,
  eventDateTime,
  serverUrl,
  eventId
) {
  if (!videoCountdownContainer || !videoCountdownTimer) {
    console.error(`Video countdown elements not found for event ${eventId}`);
    return;
  }

  console.log(
    `Updating video countdown for event ${eventId}, container:`,
    videoCountdownContainer
  );
  clearInterval(countdownIntervals[eventId]);

  const interval = setInterval(() => {
    const now = new Date().getTime();
    const timeLeft = eventDateTime.getTime() - now;

    if (timeLeft < 1000) {
      const videoIframe =
        domCache.videoIframe || document.getElementById("video-iframe");
      if (videoIframe) videoIframe.src = "";
    }

    if (timeLeft <= 0) {
      clearInterval(interval);
      videoCountdownContainer.style.display = "none";
      console.log(`Event started: ${eventId}`);
      const eventContainer = document.querySelector(
        `.event-container[data-id="${eventId}"]`
      );
      if (eventContainer) {
        loadEventVideo(eventContainer, serverUrl, false);
        const durationMs =
          parseFloat(eventContainer.getAttribute("data-duration")) *
            60 *
            60 *
            1000 || 12600000;
        const endTime = new Date(eventDateTime.getTime() + durationMs);
        setTimeout(() => {
          const now = new Date();
          if (now >= endTime && activeEventId === eventId) {
            markEventAsEnded(eventId);
            redirectToEndedURL();
          }
        }, durationMs);
      }
    } else {
      const days = Math.floor(timeLeft / 86400000);
      const hours = Math.floor((timeLeft % 86400000) / 3600000);
      const minutes = Math.floor((timeLeft % 3600000) / 60000);
      const seconds = Math.floor((timeLeft % 60000) / 1000);
      videoCountdownContainer.style.display = "block";
      const countdownText = `${days}d ${hours}h ${minutes}m ${seconds}s`;
      videoCountdownTimer.innerHTML = countdownText;
      console.log(`Countdown for event ${eventId}: ${countdownText}`);
    }
  }, 1000);

  countdownIntervals[eventId] = interval;
}

// Loads video for an event or channel
function loadEventVideo(container, serverUrl = null, updateSession = true) {
  try {
    const id = container.getAttribute("data-id");
    const savedServerUrl = sessionStorage.getItem(`activeServerUrl_${id}`);
    const videoUrl =
      serverUrl ||
      savedServerUrl ||
      container.getAttribute("data-url") ||
      "https://listcanal.blogspot.com/";
    const isChannel = container.classList.contains("channel-container");
    const matchDate = container
      .querySelector(".match-date")
      ?.getAttribute("data-original-date");
    const matchTime = container
      .querySelector(".match-time")
      ?.getAttribute("data-original-time");
    const duration = parseFloat(container.getAttribute("data-duration")) || 3.5;
    const durationMs = duration * 60 * 60 * 1000;
    const eventDateTime =
      !isChannel && matchDate && matchTime
        ? parseEventDateTime(matchDate, matchTime)
        : null;
    const now = new Date();

    if (!isChannel && (!eventDateTime || isNaN(eventDateTime.getTime()))) {
      console.error(
        `Invalid event time for event ${id}: ${matchDate} ${matchTime}`
      );
      return;
    }

    if (updateSession) {
      if (isChannel) {
        sessionStorage.setItem("activeChannelId", id);
        sessionStorage.removeItem("activeEventId");
      } else {
        sessionStorage.setItem("activeEventId", id);
        sessionStorage.removeItem("activeChannelId");
        activeEventId = id;
      }
    }

    const videoCountdownContainer =
      domCache.videoCountdownContainer ||
      document.getElementById("video-countdown");
    const videoCountdownTimer =
      domCache.videoCountdownTimer ||
      videoCountdownContainer?.querySelector(".countdown-timer");
    const videoIframe =
      domCache.videoIframe || document.getElementById("video-iframe");
    const videoPlaceholder =
      domCache.videoPlaceholder || document.getElementById("video-placeholder");

    if (!videoIframe || !videoPlaceholder || !videoCountdownContainer) {
      console.error("Required video elements not found");
      return;
    }

    if (!videoUrl || videoUrl === "about:blank") {
      console.error(`Invalid video URL for ${id}: ${videoUrl}`);
      videoIframe.src = "https://listcanal.blogspot.com/";
      videoIframe.style.display = "block";
      videoPlaceholder.style.display = "none";
      videoCountdownContainer.style.display = "none";
      return;
    }

    document.querySelectorAll(".countdown-wrapper").forEach((wrapper) => {
      wrapper.style.display = "none";
    });

    for (const intervalId in countdownIntervals) {
      clearInterval(countdownIntervals[intervalId]);
    }

    document
      .querySelectorAll(".event-container .server-buttons")
      .forEach((buttons) => {
        buttons.style.display = "none";
      });

    if (isChannel) {
      videoIframe.src = videoUrl;
      videoIframe.style.display = "block";
      videoPlaceholder.style.display = "none";
      videoCountdownContainer.style.display = "none";
      console.log(`Channel video loaded: ${videoUrl}`);
      return;
    }

    if (now >= eventDateTime) {
      const endTime = new Date(eventDateTime.getTime() + durationMs);
      if (now >= endTime) {
        console.log(`Event ${id} has ended at ${endTime}`);
        markEventAsEnded(id);
        return;
      }
      videoCountdownContainer.style.display = "none";
      videoIframe.src = videoUrl;
      videoIframe.style.display = "block";
      videoPlaceholder.style.display = "none";
      setActiveHoverEffect(id);
      console.log(`Loading event video now: ${id}, URL: ${videoUrl}`);
      toggleServerButtons(container, true);
      console.log(
        `Showing server buttons for live event ${id} in loadEventVideo`
      );
      const serverButton = container.querySelector(
        `.server-button[data-url="${videoUrl}"]`
      );
      if (serverButton) selectServerButton(serverButton);
    } else {
      if (videoCountdownContainer && videoCountdownTimer) {
        updateCountdown(
          videoCountdownContainer,
          videoCountdownTimer,
          eventDateTime,
          videoUrl,
          id
        );
      }
      videoIframe.style.display = "none";
      videoPlaceholder.style.display = "block";
      setActiveHoverEffect(id);
      toggleServerButtons(container, false);
      console.log(`Setting countdown for future event: ${id}`);
    }

    if (updateSession && serverUrl) {
      sessionStorage.setItem(`activeServerUrl_${id}`, serverUrl);
    }
  } catch (error) {
    console.error("Error loading event video:", error);
  }
}

// Marks an event as ended and hides it
function markEventAsEnded(eventId) {
  const eventContainer = document.querySelector(
    `.event-container[data-id="${eventId}"]`
  );
  if (eventContainer) {
    sessionStorage.setItem(`eventStatus_${eventId}`, "ended");
    eventContainer.style.display = "none";
    console.log(`Event ${eventId} marked as ended and hidden`);
    checkNoEventsMessage();
  }
}

// Redirects to an ended URL if the active event has ended
function redirectToEndedURL() {
  const eventId = sessionStorage.getItem("activeEventId");
  const eventStatus = sessionStorage.getItem(`eventStatus_${eventId}`);
  if (eventStatus === "ended") {
    const eventContainer = document.querySelector(
      `.event-container[data-id="${eventId}"]`
    );
    if (eventContainer) {
      eventContainer.style.display = "none";
    }
    console.log(`Redirecting for ended event: ${eventId}`);
  }
}

// Sets the hover effect for the active event
function setActiveHoverEffect(eventId) {
  document.querySelectorAll(".event-container").forEach((container) => {
    container.classList.remove("hover-effect");
  });

  const activeContainer = document.querySelector(
    `.event-container[data-id="${eventId}"]`
  );
  if (activeContainer) {
    activeContainer.classList.add("hover-effect");
  }
}

// Toggles the visibility of server buttons
function toggleServerButtons(container, show) {
  const buttons = container.querySelector(".server-buttons");
  if (buttons) {
    buttons.style.display = show ? "flex" : "none";
  }
}

// Selects a server button and updates styling
function selectServerButton(button) {
  const container = button.closest(".buttons-container");
  if (container) {
    container.querySelectorAll(".server-button").forEach((btn) => {
      btn.classList.remove("active");
    });
    button.classList.add("active");
  }
}

// Starts periodic check for event status
function startPeriodicEventCheck() {
  setInterval(() => {
    const now = new Date();
    document.querySelectorAll(".event-container").forEach((container) => {
      const eventId = container.getAttribute("data-id");
      if (sessionStorage.getItem(`eventStatus_${eventId}`) === "ended") return;

      const matchDate = container
        .querySelector(".match-date")
        ?.getAttribute("data-original-date");
      const matchTime = container
        .querySelector(".match-time")
        ?.getAttribute("data-original-time");

      if (matchDate && matchTime) {
        const matchDateTime = parseEventDateTime(matchDate, matchTime);
        const duration =
          parseFloat(container.getAttribute("data-duration")) || 3.5;
        const durationMs = duration * 60 * 60 * 1000;
        const endTime = new Date(matchDateTime.getTime() + durationMs);

        if (now >= endTime) {
          markEventAsEnded(eventId);
          if (activeEventId === eventId) redirectToEndedURL();
        } else if (now >= matchDateTime) {
          const liveLabel = container.querySelector(".live-label");
          if (liveLabel && liveLabel.style.display === "none") {
            liveLabel.style.display = "block";
            console.log(`Event ${eventId} is now LIVE`);
          }
        }
      }
    });
  }, 60000); // Check every minute
}

// Helper function to setup channel click events
function setupChannels() {
  const channelContainers = document.querySelectorAll(".channel-container");
  channelContainers.forEach((container) => {
    container.addEventListener("click", () => {
      loadEventVideo(container);

      // Update UI selection
      channelContainers.forEach((c) => c.classList.remove("selected"));
      container.classList.add("selected");
    });

    // Restore selection if active
    const channelId = container.getAttribute("data-id");
    if (sessionStorage.getItem("activeChannelId") === channelId) {
      container.classList.add("selected");
      loadEventVideo(container, null, false);
    }
  });
}

// Switch content tabs
function switchContent(tabId) {
  document.querySelectorAll(".sidebar-content").forEach((content) => {
    content.classList.remove("active");
  });

  document.querySelectorAll(".menu-button").forEach((button) => {
    button.style.backgroundColor = "";
    button.style.color = "";
  });

  const activeContent = document.getElementById(tabId);
  if (activeContent) {
    activeContent.classList.add("active");
  }

  // Highlight active button logic could be added here if needed
}

// Initialize app
document.addEventListener("DOMContentLoaded", () => {
  initDomCache();
  loadEvents();
  loadChannels();

  // Set initial active tab
  const activeTab = sessionStorage.getItem("activeTab") || "live-event";
  switchContent(activeTab);

  // Add click listeners to menu buttons to save state
  document.querySelectorAll(".menu-button").forEach((button) => {
    button.addEventListener("click", (e) => {
      const onclick = button.getAttribute("onclick");
      if (onclick && onclick.includes("switchContent")) {
        const tabId = onclick.match(/'([^']+)'/)[1];
        sessionStorage.setItem("activeTab", tabId);
      }
    });
  });
});
