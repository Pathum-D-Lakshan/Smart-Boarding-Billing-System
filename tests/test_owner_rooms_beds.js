/* Run with the actual controller source; DOM mocks check label behaviour only. */
function runRoomsUiTests(source) {
    const checks = [];
    function assert(condition, message) { if (!condition) throw new Error(message); }
    function page(type) {
        const elements = {
            room_type: { value: type, addEventListener(event, handler) { this.change = handler; } },
            "room-rent-label": { textContent: "" },
            "room-rent-hint": { textContent: "" },
        };
        new Function("document", source)({ getElementById(id) { return elements[id]; } });
        return elements;
    }
    let elements = page("shared");
    assert(elements["room-rent-label"].textContent === "Monthly Rent per Bed (LKR)", "Shared label must use per-bed pricing.");
    assert(elements["room-rent-hint"].textContent.includes("default rent for new beds"), "Shared price must be described as a default.");
    checks.push("Shared room price label and default-rent explanation");
    elements = page("private");
    assert(elements["room-rent-label"].textContent === "Monthly Rent per Room (LKR)", "Private label must use per-room pricing.");
    assert(elements["room-rent-hint"].textContent.includes("not separately rentable"), "Private physical beds cannot be separately rentable.");
    checks.push("Private room price label and physical-bed explanation");
    elements.room_type.value = "shared";
    elements.room_type.change();
    assert(elements["room-rent-label"].textContent.includes("per Bed"), "Switching back must restore the bed unit.");
    elements.room_type.value = "private";
    elements.room_type.change();
    assert(elements["room-rent-label"].textContent.includes("per Room"), "Switching to Private must restore the room unit.");
    checks.push("Changing room type updates the rent unit in both directions");
    new Function("document", source)({ getElementById() { return null; } });
    checks.push("Safe initialization on pages without a room form");
    return { passed: checks.length, checks };
}
