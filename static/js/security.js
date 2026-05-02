// Page type detection for screenshot protection
(function() {
    const runWhenBodyReady = function(callback) {
        if (document.body) {
            callback(document.body);
            return;
        }
        document.addEventListener('DOMContentLoaded', function onReady() {
            document.removeEventListener('DOMContentLoaded', onReady);
            if (document.body) {
                callback(document.body);
            }
        });
    };

    const withBody = function(callback) {
        const body = document.body;
        if (body) {
            callback(body);
        }
    };

    // Detect page type from URL
    const currentPath = window.location.pathname;
    let pageType = 'normal';
    let isSensitive = false;
    
    // Define sensitive page patterns
    const sensitivePages = {
        payment: ['/payments/', '/checkout/', '/escrow/', '/wallet/'],
        profile: ['/profile/', '/settings/', '/documents/', '/kyc/'],
        contract: ['/contract/', '/agreement/', '/legal/'],
        admin: ['/admin/', '/verify/', '/audit/'],
        transaction: ['/transaction/', '/deal/', '/closing/']
    };
    
    // Check if current page is sensitive
    for (const [type, patterns] of Object.entries(sensitivePages)) {
        for (const pattern of patterns) {
            if (currentPath.includes(pattern)) {
                isSensitive = true;
                pageType = type;
                break;
            }
        }
        if (isSensitive) break;
    }
    
    // Add class to body for CSS protection
    if (isSensitive) {
        runWhenBodyReady(function(body) {
            body.classList.add('sensitive-page');
            body.classList.add(`${pageType}-page`);
            body.setAttribute('data-page-type', pageType);

            // Add user-specific watermark
            const username = body.getAttribute('data-username') || "Guest";
            const watermarkText = `${username} | ${new Date().toISOString().slice(0,19)} | ${window.location.hostname}`;
            body.setAttribute('data-watermark-enabled', 'true');
            body.setAttribute('data-watermark-text', watermarkText);
        });
    }
    
    // Detect screenshot key combinations
    let screenshotAttempts = 0;
    
    document.addEventListener('keydown', function(e) {
        // Detect PrintScreen key
        if (e.key === 'PrintScreen') {
            e.preventDefault();
            screenshotAttempts++;
            withBody(function(body) {
                body.classList.add('screenshot-attempt');
            });
            setTimeout(() => {
                withBody(function(body) {
                    body.classList.remove('screenshot-attempt');
                });
            }, 500);
            
            // Log screenshot attempt
            if (window.logScreenshotAttempt) {
                window.logScreenshotAttempt();
            }
            return false;
        }
        
        // Detect Ctrl+Shift+S or Cmd+Shift+S (macOS screenshot)
        if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 's' || e.key === 'S')) {
            e.preventDefault();
            screenshotAttempts++;
            withBody(function(body) {
                body.classList.add('screenshot-attempt');
            });
            setTimeout(() => {
                withBody(function(body) {
                    body.classList.remove('screenshot-attempt');
                });
            }, 500);
            return false;
        }
    });
    
    // Detect right-click
    document.addEventListener('contextmenu', function(e) {
        // Allow right-click on inputs and textareas
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
            return true;
        }
        
        // Prevent on sensitive pages
        if (isSensitive) {
            e.preventDefault();
            return false;
        }
    });
    
    // Optional: Detect if DevTools is open (basic detection)
    let devtoolsOpen = false;
    const element = new Image();
    Object.defineProperty(element, 'id', {
        get: function() {
            devtoolsOpen = true;
            withBody(function(body) {
                body.classList.add('devtools-open');
            });
        }
    });
    
    setInterval(() => {
        devtoolsOpen = false;
        console.log(element);
        console.clear();
        if (devtoolsOpen) {
            withBody(function(body) {
                body.classList.add('devtools-open');
            });
        } else {
            withBody(function(body) {
                body.classList.remove('devtools-open');
            });
        }
    }, 1000);
    
    // Function to log screenshot attempts (optional AJAX call)
    window.logScreenshotAttempt = function() {
        if (isSensitive) {
            const csrfInput = document.querySelector('[name=csrfmiddlewaretoken]');
            fetch('/api/log-screenshot-attempt/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfInput ? csrfInput.value : ''
                },
                body: JSON.stringify({
                    page: currentPath,
                    timestamp: new Date().toISOString(),
                    userAgent: navigator.userAgent
                })
            }).catch(() => {});
        }
    };
})();
