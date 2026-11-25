(() => {
    const selector = "img[data-boarding-photo]";

    function showPlaceholder(image) {
        image.hidden = true;
        image.nextElementSibling.hidden = false;
    }

    // A cover can be removed after the page renders, or fail to decode in the browser.
    document.addEventListener("error", event => {
        if (event.target.matches?.(selector)) showPlaceholder(event.target);
    }, true);

    for (const image of document.querySelectorAll(selector)) {
        if (image.complete && !image.naturalWidth) showPlaceholder(image);
    }
})();
