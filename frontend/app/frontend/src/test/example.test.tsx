import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "./testUtils";

import { Example } from "../components/Example";

describe("Example", () => {
    it("renders the example text", () => {
        renderWithProviders(<Example text="What is GraphRAG?" value="What is GraphRAG?" onClick={vi.fn()} />);
        expect(screen.getByText("What is GraphRAG?")).toBeInTheDocument();
    });

    it("calls onClick with value when clicked", async () => {
        const user = userEvent.setup();
        const onClick = vi.fn();
        renderWithProviders(<Example text="Example Q" value="example-value" onClick={onClick} />);
        await user.click(screen.getByText("Example Q"));
        expect(onClick).toHaveBeenCalledWith("example-value");
    });
});
