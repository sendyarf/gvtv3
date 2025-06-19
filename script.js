// Global object to store countdown intervals
let countdownIntervals = {};
// Tracks the currently active event ID
let activeEventId = null;

// Loads channel data from channels.json
async function loadChannels() {
    try {
        const response = await fetch('channels.json');
        const channels = await response.json();
        const liveTvContent = document.querySelector("#live-tv #content");
        console.log("Live TV Content Element:", liveTvContent);
        if (!liveTvContent) throw new Error("Live TV content element not found");
        liveTvContent.innerHTML = '';
        channels.forEach(channel => {
            const channelHtml = `
                <div class="channel-container" data-id="${channel.id}" data-url="${channel.url}">
                    <div class="logo-container">
                        <img src="${channel.logo}" alt="Channel Logo" class="logo">
                    </div>
                    <div class="info-container">
                        <h3 class="channel-name">${channel.name}</h3>
                        <p class="status">${channel.status}</p>
                    </div>
                </div>
            `;
            liveTvContent.insertAdjacentHTML('beforeend', channelHtml);
        });
        liveTvContent.insertAdjacentHTML('beforeend', '<div class="spacer"></div>');
        setupChannels();
    } catch (error) {
        console.error("Error loading channels:", error);
    }
}

// Checks if event has ended based on match_date, match_time, and duration
function isEventEnded(event) {
    const matchDateTime = parseEventDateTime(event.match_date, event.match_time);
    const duration = parseFloat(event.duration) || 3.5;
    const durationMs = duration * 60 * 60 * 1000;
    const endTime = new Date(matchDateTime.getTime() + durationMs);
    const now = new Date();
    return now >= endTime;
}

// Loads event data from event.json
async function loadEvents() {
    try {
        const response = await fetch('event.json');
        const events = await response.json();
        const liveEventContent = document.querySelector("#live-event #content");
        console.log("Live Event Content Element:", liveEventContent);
        if (!liveEventContent) throw new Error("Live event content element not found");
        console.log("Events:", events);
        liveEventContent.innerHTML = '';

        const validEvents = events.filter(event => {
            const ended = isEventEnded(event);
            if (ended) {
                console.log(`Event ${event.id} has ended and will not be rendered`);
                sessionStorage.setItem(`eventStatus_${event.id}`, 'ended');
            }
            return !ended;
        });

        const sortedEvents = validEvents.slice().sort((a, b) => {
            const dateTimeA = parseEventDateTime(a.match_date, a.match_time);
            const dateTimeB = parseEventDateTime(b.match_date, b.match_time);
            return dateTimeA.getTime() - dateTimeB.getTime();
        });

        sortedEvents.forEach(event => {
            const validServers = event.servers.filter(server => server.url && server.label && server.label.trim() !== '');
            const defaultServerUrl = validServers[0]?.url || '';
            const serverListJson = encodeURIComponent(JSON.stringify(validServers));

            const eventHtml = `
                <div class="event-container" data-id="${event.id}" data-url="${defaultServerUrl}" data-servers="${serverListJson}" data-duration="${event.duration}">
                    <div class="event-header">
                        <div class="league-info">
                            <img src="${event.icon}" class="sport-icon" onerror="this.src='https://placehold.co/30x30/png?text=Icon';">
                            <span class="league-name">${event.league}</span>
                        </div>
                        <button class="copy-url-button" data-id="${event.id}" title="Copy event URL">
                            <i class="fa-solid fa-copy"></i>
                        </button>
                    </div>
                    <div class="event-details">
                        <div class="team-left">
                            <img src="${event.team1.logo}" class="team-logo" alt="${event.team1.name}" onerror="this.src='https://placehold.co/50x50/png?text=Team';">
                            <span class="team-name">${event.team1.name}</span>
                        </div>
                        <div class="match-info">
                            <div class="kickoff-match-date">${event.kickoff_date}</div>
                            <div class="kickoff-match-time">${event.kickoff_time}</div>
                            <div class="live-label" style="display:none;">Live</div>
                            <div class="match-date" data-original-date="${event.match_date}" style="display:none;">${event.match_date}</div>
                            <div class="match-time" data-original-time="${event.match_time}" style="display:none;">${event.match_time}</div>
                        </div>
                        <div class="team-right">
                            <img src="${event.team2.logo}" class="team-logo" alt="${event.team2.name}" onerror="this.src='https://placehold.co/50x50/png?text=Team';">
                            <span class="team-name">${event.team2.name}</span>
                        </div>
                    </div>
                    <div class="server-buttons" style="display:none;">
                        <div class="buttons-container"></div>
                    </div>
                </div>
            `;
            liveEventContent.insertAdjacentHTML('beforeend', eventHtml);
            console.log(`Event Created: ${event.id}`);

            const eventContainer = liveEventContent.querySelector(`.event-container[data-id="${event.id}"]`);
            const buttonsContainer = eventContainer.querySelector('.buttons-container');
            if (!buttonsContainer) {
                console.error(`Buttons container not found for event ${event.id}`);
                return;
            }
            validServers.forEach((server, index) => {
                const button = document.createElement('div');
                button.className = 'server-button';
                if (index === 0) button.classList.add('active');
                button.setAttribute('data-url', server.url);
                button.textContent = server.label;
                buttonsContainer.appendChild(button);
                console.log(`Server button created for ${event.id}: ${server.label} (${server.url})`);
            });
        });

        liveEventContent.insertAdjacentHTML('beforeend', '<div class="spacer"></div>');
        setupEvents();
        setupCopyButtons(); // Initialize copy buttons

        const savedEventId = sessionStorage.getItem('activeEventId');
        const savedServerUrl = sessionStorage.getItem(`activeServerUrl_${savedEventId}`);
        if (savedEventId && savedServerUrl) {
            const eventContainer = document.querySelector(`.event-container[data-id="${savedEventId}"]`);
            if (eventContainer) {
                const serverButton = eventContainer.querySelector(`.server-button[data-url="${savedServerUrl}"]`);
                if (serverButton) selectServerButton(serverButton);
                loadEventVideo(eventContainer, savedServerUrl, false);
                const matchDate = eventContainer.querySelector('.match-date')?.getAttribute('data-original-date');
                const matchTime = eventContainer.querySelector('.match-time')?.getAttribute('data-original-time');
                const matchDateTime = parseEventDateTime(matchDate, matchTime);
                if (new Date() >= matchDateTime) {
                    toggleServerButtons(eventContainer, true);
                    console.log(`Restored server buttons for saved event ${savedEventId}`);
                }
            }
        }

        // Handle URL-based event loading
        const path = window.location.pathname;
        const eventIdFromUrl = path.replace(/^\/+/, '');
        console.log("Event ID from URL:", eventIdFromUrl);
        if (eventIdFromUrl) {
            const eventContainer = document.querySelector(`.event-container[data-id="${eventIdFromUrl}"]`);
            if (eventContainer) {
                const savedServerUrl = sessionStorage.getItem(`activeServerUrl_${eventIdFromUrl}`);
                const defaultServerUrl = eventContainer.getAttribute('data-url');
                const videoUrl = savedServerUrl || defaultServerUrl;
                const serverButton = eventContainer.querySelector(`.server-button[data-url="${videoUrl}"]`);
                if (serverButton) selectServerButton(serverButton);
                loadEventVideo(eventContainer, videoUrl, false);
                const matchDate = eventContainer.querySelector('.match-date')?.getAttribute('data-original-date');
                const matchTime = eventContainer.querySelector('.match-time')?.getAttribute('data-original-time');
                const matchDateTime = parseEventDateTime(matchDate, matchTime);
                if (new Date() >= matchDateTime) {
                    toggleServerButtons(eventContainer, true);
                    console.log(`Showing server buttons for URL-loaded event ${eventIdFromUrl}`);
                }
                sessionStorage.setItem('activeEventId', eventIdFromUrl);
                sessionStorage.removeItem('activeChannelId');
                setActiveHoverEffect(eventIdFromUrl);
                switchContent('live-event');
            } else {
                console.warn(`No event found for ID: ${eventIdFromUrl}`);
            }
        }
    } catch (error) {
        console.error("Error loading events:", error);
    }
}

// Sets up event listeners for copy buttons
function setupCopyButtons() {
    const copyButtons = document.querySelectorAll('.copy-url-button');
    console.log("Copy Buttons Found:", copyButtons.length);
    copyButtons.forEach(button => {
        button.addEventListener('click', (event) => {
            event.stopPropagation(); // Prevent triggering event container click
            const eventId = button.getAttribute('data-id');
            const eventUrl = `${window.location.origin}/${eventId}`;
            navigator.clipboard.writeText(eventUrl).then(() => {
                console.log(`Copied URL for event ${eventId}: ${eventUrl}`);
                // Provide visual feedback
                const icon = button.querySelector('i');
                icon.classList.remove('fa-copy');
                icon.classList.add('fa-check');
                setTimeout(() => {
                    icon.classList.remove('fa-check');
                    icon.classList.add('fa-copy');
                }, 2000);
            }).catch(err => {
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
    const eventContainers = document.querySelectorAll('.event-container');
    console.log("Event Containers Found:", eventContainers.length);
    const eventIds = [];
    eventContainers.forEach(container => {
        const eventId = container.getAttribute('data-id');
        eventIds.push(eventId);

        const matchDate = container.querySelector('.match-date').dataset.originalDate;
        const matchTime = container.querySelector('.match-time').dataset.originalTime;
        const kickoffDate = container.querySelector('.kickoff-match-date').textContent.trim();
        const kickoffTime = container.querySelector('.kickoff-match-time').textContent.trim();
        const matchDateTime = parseEventDateTime(matchDate, matchTime);
        const kickoffDateTime = parseEventDateTime(kickoffDate, kickoffTime);
        const duration = parseFloat(container.getAttribute('data-duration')) || 3.5;
        const durationMs = duration * 60 * 60 * 1000;

        updateMatchTimes(container, matchDateTime);
        updateMatchTimes(container, kickoffDateTime);
        checkLiveStatus(container, matchDateTime, durationMs);

        const eventStatus = sessionStorage.getItem(`eventStatus_${eventId}`);
        if (eventStatus === 'ended') {
            markEventAsEnded(eventId);
            if (activeEventId === eventId) redirectToEndedURL();
        }

        let servers;
        try {
            const serverData = decodeURIComponent(container.getAttribute('data-servers'));
            console.log(`Raw data-servers for ${eventId}:`, serverData);
            servers = JSON.parse(serverData);
        } catch (e) {
            console.error(`Error parsing servers for event ${eventId}:`, e);
            servers = [];
        }
        const buttonsContainer = container.querySelector('.buttons-container');
        if (buttonsContainer) {
            const existingButtons = buttonsContainer.querySelectorAll('.server-button');
            existingButtons.forEach((button, index) => {
                if (servers[index] && servers[index].label.includes('Mobile') && !isMobileDevice()) {
                    button.style.display = 'none';
                    return;
                }
                button.style.display = '';
                const newButton = button.cloneNode(true);
                button.parentNode.replaceChild(newButton, button);
                newButton.addEventListener('click', (event) => {
                    event.stopPropagation();
                    selectServerButton(newButton);
                    loadEventVideo(container, newButton.getAttribute('data-url'));
                    console.log(`Server selected for ${eventId}: ${newButton.textContent} (${newButton.getAttribute('data-url')})`);
                });
                if (index === 0) newButton.classList.add('active');
            });
        }

        container.addEventListener('click', () => {
            const now = new Date();
            document.querySelectorAll('.event-container .server-buttons').forEach(buttons => {
                buttons.style.display = 'none';
            });
            if (now >= matchDateTime) {
                toggleServerButtons(container, true);
            }
            loadEventVideo(container);
        });

        const savedEventId = sessionStorage.getItem('activeEventId');
        const savedServerUrl = sessionStorage.getItem(`activeServerUrl_${eventId}`);
        if (savedEventId === eventId && savedServerUrl) {
            const serverButton = container.querySelector(`.server-button[data-url="${savedServerUrl}"]`);
            if (serverButton) {
                selectServerButton(serverButton);
                loadEventVideo(container, savedServerUrl, false);
                if (new Date() >= matchDateTime) {
                    toggleServerButtons(container, true);
                    console.log(`Restored server buttons for saved event ${eventId}`);
                }
            }
        }
    });

    if (activeEventId && !eventIds.includes(activeEventId)) {
        redirectToEndedURL();
    }

    startPeriodicEventCheck();
}

// Parses date and time strings into a Date object
function parseEventDateTime(dateStr, timeStr) {
    const dateTime = new Date(`${dateStr}T${timeStr}:00+07:00`);
    console.log(`Parsed DateTime for ${dateStr} ${timeStr}:`, dateTime);
    return dateTime;
}

// Updates the countdown timer for an event
function updateCountdown(videoCountdownContainer, videoCountdownTimer, eventDateTime, serverUrl, eventId) {
    if (!videoCountdownContainer || !videoCountdownTimer) {
        console.error(`Video countdown elements not found for event ${eventId}`);
        return;
    }
    console.log(`Updating video countdown for event ${eventId}, container:`, videoCountdownContainer);
    clearInterval(countdownIntervals[eventId]);
    const interval = setInterval(() => {
        const now = new Date().getTime();
        const timeLeft = eventDateTime.getTime() - now;

        if (timeLeft < 1000) {
            const videoIframe = document.getElementById('video-iframe');
            if (videoIframe) videoIframe.src = '';
        }

        if (timeLeft <= 0) {
            clearInterval(interval);
            videoCountdownContainer.style.display = 'none';
            console.log(`Event started: ${eventId}`);
            const eventContainer = document.querySelector(`.event-container[data-id="${eventId}"]`);
            if (eventContainer) {
                loadEventVideo(eventContainer, serverUrl, false);
                checkLiveStatus(eventContainer, eventDateTime, (parseFloat(eventContainer.getAttribute('data-duration')) || 3.5) * 60 * 60 * 1000);
                const serverButton = eventContainer.querySelector('.server-button');
                if (serverButton) selectServerButton(serverButton);
                toggleServerButtons(eventContainer, true);
                console.log(`Showing server buttons for event ${eventId} after countdown`);
                const durationMs = (parseFloat(eventContainer.getAttribute('data-duration')) * 60 * 60 * 1000) || 12600000;
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
            videoCountdownContainer.style.display = 'block';
            const countdownText = `${days}d ${hours}h ${minutes}m ${seconds}s`;
            videoCountdownTimer.innerHTML = countdownText;
            console.log(`Countdown for event ${eventId}: ${countdownText}`);
        }
    }, 1000);
    countdownIntervals[eventId] = interval;
}

// Updates match date and time displays based on user's timezone
function updateMatchTimes(container, eventDateTime) {
    const matchDateEl = container.querySelector('.match-date');
    const matchTimeEl = container.querySelector('.match-time');
    const kickoffDateEl = container.querySelector('.kickoff-match-date');
    const kickoffTimeEl = container.querySelector('.kickoff-match-time');

    if (!matchDateEl || !matchTimeEl) return;

    if (!matchDateEl.hasAttribute('data-original-date')) {
        matchDateEl.setAttribute('data-original-date', matchDateEl.textContent.trim());
        matchTimeEl.setAttribute('data-original-time', matchTimeEl.textContent.trim());
    }

    const adjustedTime = new Date(eventDateTime.getTime() + eventDateTime.getTimezoneOffset() * 60000);
    const localOffset = new Date().getTimezoneOffset() / 60;
    const localTime = new Date(adjustedTime.getTime() - localOffset * 60 * 60 * 1000);
    const formattedDate = localTime.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
    const formattedTime = localTime.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });

    console.log(`Adjusted date for event: ${formattedDate}`);
    console.log(`Adjusted time for event: ${formattedTime}`);
    matchDateEl.textContent = formattedDate;
    matchTimeEl.textContent = formattedTime;
    if (kickoffDateEl && kickoffTimeEl) {
        kickoffDateEl.textContent = formattedDate;
        kickoffTimeEl.textContent = formattedTime;
    }
}

// Checks if an event is live and updates its status
function checkLiveStatus(container, eventDateTime, durationMs) {
    const now = new Date();
    const liveLabel = container.querySelector('.live-label');
    const eventId = container.getAttribute('data-id');
    if (!liveLabel) return;
    console.log(`Checking live status for ${eventId}: now=${now}, eventDateTime=${eventDateTime}`);
    if (now >= eventDateTime) {
        liveLabel.style.display = 'block';
        console.log(`Event live: ${eventId}`);
        toggleServerButtons(container, true);
        console.log(`Showing server buttons for live event ${eventId}`);
        const endTime = new Date(eventDateTime.getTime() + durationMs);
        if (now >= endTime) {
            console.log(`Event ${eventId} has ended at ${endTime}`);
            markEventAsEnded(eventId);
        } else {
            setTimeout(() => {
                const currentTime = new Date();
                if (currentTime >= endTime) {
                    console.log(`Event ${eventId} has ended at ${endTime}`);
                    markEventAsEnded(eventId);
                }
            }, endTime.getTime() - now.getTime());
        }
    } else {
        liveLabel.style.display = 'none';
        console.log(`Event not live yet: ${eventId}`);
        toggleServerButtons(container, false);
        setTimeout(() => {
            checkLiveStatus(container, eventDateTime, durationMs);
        }, eventDateTime.getTime() - now.getTime());
    }
}

// Sets up event listeners for channel containers
function setupChannels() {
    const channelContainers = document.querySelectorAll('.channel-container');
    console.log("Channel Containers Found:", channelContainers.length);
    const activeChannelId = sessionStorage.getItem('activeChannelId');
    channelContainers.forEach(container => {
        const channelId = container.getAttribute('data-id');
        if (channelId === activeChannelId) {
            container.classList.add('selected');
            loadEventVideo(container);
        }
        container.addEventListener('click', () => {
            channelContainers.forEach(c => c.classList.remove('selected'));
            container.classList.add('selected');
            sessionStorage.setItem('activeChannelId', channelId);
            sessionStorage.removeItem('activeEventId');
            loadEventVideo(container);
        });
    });
}

// Loads video for an event or channel
function loadEventVideo(container, serverUrl = null, updateSession = true) {
    const id = container.getAttribute('data-id');
    const savedServerUrl = sessionStorage.getItem(`activeServerUrl_${id}`);
    const videoUrl = serverUrl || savedServerUrl || container.getAttribute('data-url') || 'https://bikinbaru96.blogspot.com/2024/06/blog-post_13.html';
    const isChannel = container.classList.contains('channel-container');
    const matchDate = container.querySelector('.match-date')?.getAttribute('data-original-date');
    const matchTime = container.querySelector('.match-time')?.getAttribute('data-original-time');
    const duration = parseFloat(container.getAttribute('data-duration')) || 3.5;
    const durationMs = duration * 60 * 60 * 1000;
    const eventDateTime = !isChannel && matchDate && matchTime ? parseEventDateTime(matchDate, matchTime) : null;
    const now = new Date();

    if (!isChannel && (!eventDateTime || isNaN(eventDateTime.getTime()))) {
        console.error(`Invalid event time for event ${id}: ${matchDate} ${matchTime}`);
        return;
    }

    if (updateSession) {
        if (isChannel) {
            sessionStorage.setItem('activeChannelId', id);
            sessionStorage.removeItem('activeEventId');
        } else {
            sessionStorage.setItem('activeEventId', id);
            sessionStorage.removeItem('activeChannelId');
            activeEventId = id;
        }
    }

    const videoCountdownContainer = document.getElementById('video-countdown');
    const videoCountdownTimer = videoCountdownContainer?.querySelector('.countdown-timer');
    const videoIframe = document.getElementById('video-iframe');
    const videoPlaceholder = document.getElementById('video-placeholder');

    if (!videoIframe || !videoPlaceholder || !videoCountdownContainer) {
        console.error("Required video elements not found");
        return;
    }

    if (!videoUrl || videoUrl === 'about:blank') {
        console.error(`Invalid video URL for ${id}: ${videoUrl}`);
        videoIframe.src = 'https://bikinbaru96.blogspot.com/2024/06/blog-post_13.html';
        videoIframe.style.display = 'block';
        videoPlaceholder.style.display = 'none';
        videoCountdownContainer.style.display = 'none';
        return;
    }

    document.querySelectorAll('.countdown-wrapper').forEach(wrapper => {
        wrapper.style.display = 'none';
    });
    for (const intervalId in countdownIntervals) {
        clearInterval(countdownIntervals[intervalId]);
    }
    document.querySelectorAll('.event-container .server-buttons').forEach(buttons => {
        buttons.style.display = 'none';
    });

    if (isChannel) {
        videoIframe.src = videoUrl;
        videoIframe.style.display = 'block';
        videoPlaceholder.style.display = 'none';
        videoCountdownContainer.style.display = 'none';
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
        videoCountdownContainer.style.display = 'none';
        videoIframe.src = videoUrl;
        videoIframe.style.display = 'block';
        videoPlaceholder.style.display = 'none';
        setActiveHoverEffect(id);
        console.log(`Loading event video now: ${id}, URL: ${videoUrl}`);
        toggleServerButtons(container, true);
        console.log(`Showing server buttons for live event ${id} in loadEventVideo`);
        checkLiveStatus(container, eventDateTime, durationMs);
        const serverButton = container.querySelector(`.server-button[data-url="${videoUrl}"]`);
        if (serverButton) selectServerButton(serverButton);
    } else {
        if (videoCountdownContainer && videoCountdownTimer) {
            updateCountdown(videoCountdownContainer, videoCountdownTimer, eventDateTime, videoUrl, id);
        }
        videoIframe.style.display = 'none';
        videoPlaceholder.style.display = 'block';
        setActiveHoverEffect(id);
        toggleServerButtons(container, false);
        console.log(`Setting countdown for future event: ${id}`);
    }

    if (updateSession && serverUrl) {
        sessionStorage.setItem(`activeServerUrl_${id}`, serverUrl);
    }
}

// Marks an event as ended and hides it
function markEventAsEnded(eventId) {
    const eventContainer = document.querySelector(`.event-container[data-id="${eventId}"]`);
    if (eventContainer) {
        sessionStorage.setItem(`eventStatus_${eventId}`, 'ended');
        eventContainer.style.display = 'none';
        console.log(`Event ${eventId} marked as ended and hidden`);
    }
}

// Redirects to an ended URL if the active event has ended
function redirectToEndedURL() {
    const eventId = sessionStorage.getItem('activeEventId');
    const eventStatus = sessionStorage.getItem(`eventStatus_${eventId}`);
    if (eventStatus === 'ended') {
        const eventContainer = document.querySelector(`.event-container[data-id="${eventId}"]`);
        if (eventContainer) {
            eventContainer.style.display = 'none';
        }
        console.log(`Redirecting for ended event: ${eventId}`);
    }
}

// Sets the hover effect for the active event
function setActiveHoverEffect(eventId) {
    document.querySelectorAll('.event-container').forEach(container => {
        container.classList.remove('hover-effect');
    });
    const eventContainer = document.querySelector(`.event-container[data-id="${eventId}"]`);
    if (eventContainer) {
        eventContainer.classList.add('hover-effect');
        console.log(`Hover effect set for event: ${eventId}`);
    }
}

// Toggles visibility of server buttons
function toggleServerButtons(container, show = true) {
    const serverButtons = container.querySelector('.server-buttons');
    if (serverButtons) {
        serverButtons.style.display = show ? 'flex' : 'none';
        console.log(`Server buttons for ${container.getAttribute('data-id')}: ${show ? 'shown' : 'hidden'}, element:`, serverButtons);
    } else {
        console.error(`Server buttons not found for ${container.getAttribute('data-id')}`);
    }
}

// Selects a server button and updates session storage
function selectServerButton(button) {
    const eventContainer = button.closest('.event-container');
    if (eventContainer) {
        eventContainer.querySelectorAll('.server-button').forEach(btn => {
            btn.classList.remove('active');
        });
    }
    button.classList.add('active');
    const url = button.getAttribute('data-url');
    const eventId = eventContainer.getAttribute('data-id');
    sessionStorage.setItem(`activeServerUrl_${eventId}`, url);
    console.log(`Server button selected: ${url} for event ${eventId}`);
}

// Switches between sidebar content sections
function switchContent(contentId) {
    console.log("Switching to content:", contentId);
    document.querySelectorAll('.sidebar-content').forEach(content => {
        content.classList.remove('active');
    });
    const contentElement = document.getElementById(contentId);
    if (contentElement) {
        contentElement.classList.add('active');
        console.log("Active content:", contentElement);
        if (contentId === 'chat') {
            const chatIframe = contentElement.querySelector('.chat-iframe');
            if (chatIframe && !chatIframe.src) {
                chatIframe.src = chatIframe.getAttribute('data-src');
            }
        }
    }
}

// Periodically checks event status
function startPeriodicEventCheck() {
    console.log("Starting periodic event check");
    setInterval(() => {
        console.log("Checking event status at", new Date());
        const now = new Date();
        document.querySelectorAll('.event-container').forEach(container => {
            const matchDate = container.querySelector('.match-date').getAttribute('data-original-date');
            const matchTime = container.querySelector('.match-time').getAttribute('data-original-time');
            const duration = parseFloat(container.getAttribute('data-duration')) || 3.5;
            const durationMs = duration * 60 * 60 * 1000;
            const eventDateTime = parseEventDateTime(matchDate, matchTime);
            const endTime = new Date(eventDateTime.getTime() + durationMs);
            if (now >= endTime) {
                console.log(`Event ${container.getAttribute('data-id')} has ended at ${endTime}`);
                markEventAsEnded(container.getAttribute('data-id'));
            }
        });
    }, 60000);
}

// Initialize on page load
window.addEventListener('DOMContentLoaded', async () => {
    console.log("DOM fully loaded");
    await loadEvents();
    await loadChannels();

    // Parse URL to extract event ID
    const path = window.location.pathname; // e.g., "/barcamadrid"
    const eventIdFromUrl = path.replace(/^\/+/, ''); // Remove leading slashes
    console.log("Event ID from URL:", eventIdFromUrl);

    if (eventIdFromUrl) {
        const eventContainer = document.querySelector(`.event-container[data-id="${eventIdFromUrl}"]`);
        if (eventContainer) {
            const savedServerUrl = sessionStorage.getItem(`activeServerUrl_${eventIdFromUrl}`);
            const defaultServerUrl = eventContainer.getAttribute('data-url');
            const videoUrl = savedServerUrl || defaultServerUrl;
            const serverButton = eventContainer.querySelector(`.server-button[data-url="${videoUrl}"]`);
            if (serverButton) selectServerButton(serverButton);
            loadEventVideo(eventContainer, videoUrl, false);
            const matchDate = eventContainer.querySelector('.match-date')?.getAttribute('data-original-date');
            const matchTime = eventContainer.querySelector('.match-time')?.getAttribute('data-original-time');
            const matchDateTime = parseEventDateTime(matchDate, matchTime);
            if (new Date() >= matchDateTime) {
                toggleServerButtons(eventContainer, true);
                console.log(`Showing server buttons for URL-loaded event ${eventIdFromUrl}`);
            }
            sessionStorage.setItem('activeEventId', eventIdFromUrl);
            sessionStorage.removeItem('activeChannelId');
            setActiveHoverEffect(eventIdFromUrl);
            switchContent('live-event');
        } else {
            console.warn(`No event found for ID: ${eventIdFromUrl}`);
            // Optional: Redirect to home or show error
            // window.location.href = 'https://govoet.pages.dev/';
        }
    } else {
        const activeEventId = sessionStorage.getItem('activeEventId');
        const activeServerUrl = sessionStorage.getItem(`activeServerUrl_${activeEventId}`);
        if (activeEventId && activeServerUrl) {
            const eventContainer = document.querySelector(`.event-container[data-id="${activeEventId}"]`);
            if (eventContainer) {
                const serverButton = eventContainer.querySelector(`.server-button[data-url="${activeServerUrl}"]`);
                if (serverButton) selectServerButton(serverButton);
                loadEventVideo(eventContainer, activeServerUrl, false);
                const matchDate = eventContainer.querySelector('.match-date')?.getAttribute('data-original-date');
                const matchTime = eventContainer.querySelector('.match-time')?.getAttribute('data-original-time');
                const matchDateTime = parseEventDateTime(matchDate, matchTime);
                if (new Date() >= matchDateTime) {
                    toggleServerButtons(eventContainer, true);
                    console.log(`Restored server buttons for saved live event ${activeEventId}`);
                }
                return;
            }
        }
        const activeChannelId = sessionStorage.getItem('activeChannelId');
        if (activeChannelId) {
            const channelContainer = document.querySelector(`.channel-container[data-id="${activeChannelId}"]`);
            if (channelContainer) {
                channelContainer.classList.add('selected');
                loadEventVideo(channelContainer);
            }
        }
    }
});